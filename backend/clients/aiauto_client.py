"""
AI-Auto Client - Stub fuer Nano Banana Pro 4K.

WICHTIG: Die genauen Feldnamen (Endpoint, Body-Keys, Response-Shape) sind
noch nicht verifiziert. Alle Annahmen sind mit `# TODO(aiauto-spec)` markiert.
Bevor der erste echte Run gemacht wird, muss die AI-Auto-API-Doc gegen diesen
Stub abgeglichen werden.

Annahmen (laut initialer Spec):
  POST {BASE_URL}/generate
  Header: Authorization: Bearer {KEY}
  Body:
    {
      "model": "nano-banana-pro-4k",
      "prompt": "...",
      "reference_images": [<base64 PNGs>],
      "aspect_ratio": "9:16",
      "resolution": "4K"
    }
  Response:
    - Sync:   {"output": [{"url": "https://..."}]}  oder  {"image_b64": "..."}
    - Async:  {"job_id": "..."}  -> polling via GET {BASE_URL}/jobs/{job_id}
              -> {"status": "succeeded"|"running"|"failed",
                  "output": [{"url": "..."}] | "image_b64": "..."}
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx

from backend.config import (
    AIAUTO_API_KEY,
    AIAUTO_BASE_URL,
    AIAUTO_MODEL,
    AIAUTO_POLL_INTERVAL_S,
    AIAUTO_POLL_TIMEOUT_S,
    AIAUTO_REQUEST_TIMEOUT_S,
    DEFAULT_ASPECT_RATIO,
    IMAGE_RESOLUTION,
    MAX_PARALLEL_AIAUTO_CALLS,
)

# Globale Drossel - alle Aufrufer teilen sich diese Semaphore.
_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_AIAUTO_CALLS)


class AIAutoError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not AIAUTO_API_KEY:
        raise AIAutoError(
            "AIAUTO_API_KEY ist nicht gesetzt. Bitte in .env eintragen."
        )
    return {
        "Authorization": f"Bearer {AIAUTO_API_KEY}",
        "Content-Type": "application/json",
    }


def _encode_reference(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


async def _extract_image_bytes(
    client: httpx.AsyncClient, payload: dict[str, Any]
) -> bytes:
    """Zieht die fertigen Image-Bytes aus einer Success-Response.

    Unterstuetzt beide Shapes: {"output": [{"url": ...}]} und
    {"image_b64": ...} (bzw. auf output-Ebene).
    """
    # TODO(aiauto-spec): Response-Shape an die echte AI-Auto-Doc anpassen.
    output = payload.get("output")
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            url = first.get("url")
            if url:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
            b64 = first.get("image_b64") or first.get("b64_json")
            if b64:
                return base64.b64decode(b64)
    b64 = payload.get("image_b64") or payload.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    url = payload.get("url")
    if url:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
    raise AIAutoError(
        f"Konnte aus AI-Auto Response keine Image-Bytes extrahieren: {payload!r}"
    )


async def _poll_job(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    """Pollt einen Async-Job bis succeeded/failed/timeout."""
    # TODO(aiauto-spec): Polling-Endpoint + Status-Feldnamen anpassen.
    deadline = asyncio.get_event_loop().time() + AIAUTO_POLL_TIMEOUT_S
    url = f"{AIAUTO_BASE_URL}/jobs/{job_id}"
    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise AIAutoError(f"AI-Auto job {job_id} timed out after {AIAUTO_POLL_TIMEOUT_S}s")
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        status = str(data.get("status", "")).lower()
        if status in ("succeeded", "success", "completed", "done"):
            return data
        if status in ("failed", "error", "cancelled"):
            raise AIAutoError(
                f"AI-Auto job {job_id} failed: {data.get('error') or data}"
            )
        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)


async def generate_image(
    prompt: str,
    output_path: Path,
    reference_images: list[Path] | None = None,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str = IMAGE_RESOLUTION,
) -> Path:
    """Generiert ein Bild und schreibt es nach output_path.

    Wenn das Ziel existiert, wird es ueberschrieben. Reference images werden
    als base64 in den Body gepackt.
    """
    ref_b64 = [_encode_reference(p) for p in (reference_images or []) if p.exists()]

    # TODO(aiauto-spec): Body-Keys an die echte AI-Auto-Doc anpassen.
    body = {
        "model": AIAUTO_MODEL,
        "prompt": prompt,
        "reference_images": ref_b64,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }

    url = f"{AIAUTO_BASE_URL}/generate"

    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, headers=_headers(), json=body)
            if resp.status_code >= 400:
                raise AIAutoError(
                    f"AI-Auto {resp.status_code}: {resp.text[:500]}"
                )
            data = resp.json()

            # Async-Shape erkennen: hat job_id und keinen output?
            job_id = data.get("job_id") or data.get("id")
            has_output_now = bool(data.get("output") or data.get("image_b64"))
            if job_id and not has_output_now:
                data = await _poll_job(client, str(job_id))

            image_bytes = await _extract_image_bytes(client, data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path
