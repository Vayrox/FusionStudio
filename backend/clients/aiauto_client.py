"""
AI-Auto Client fuer Image-Generation mit Nano Banana Pro.

Basiert auf der offiziellen AI-Auto SaaS-Doc:
  Base URL: https://api.ai-auto.io/api/saas
  POST /generate                       - neuen Job starten
  GET  /generations/{id}/image         - fertiges Bild (JPEG)
  GET  /generations/{id}                - Status (optional)

Image-Generation-Body:
  {
    "prompt": "...",
    "mode": "images",
    "model": "standard",
    "image_model": "nano_banana_pro",
    "aspect_ratio": "9:16",
    "resolution": "2k",
    "i2v_reference_images": ["data:image/png;base64,...", ...]
  }

Response (202 Accepted):
  {"generation": {"id": "...", "status": "pending", ...}, "status": "accepted"}

Dann /generations/{id}/image pollen bis 200 image/jpeg zurueckkommt.
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from backend.config import (
    AIAUTO_POLL_INTERVAL_S,
    AIAUTO_POLL_TIMEOUT_S,
    AIAUTO_REQUEST_TIMEOUT_S,
    DEFAULT_ASPECT_RATIO,
    MAX_PARALLEL_AIAUTO_CALLS,
    settings,
)

_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_AIAUTO_CALLS)


class AIAutoError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    key = settings.aiauto_api_key
    if not key:
        raise AIAutoError(
            "AIAUTO_API_KEY ist nicht gesetzt. Im Dashboard unter Settings eintragen."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _encode_reference_as_data_url(image_path: Path) -> str:
    """Packt ein lokales Bild in eine base64-Data-URL (wie AI-Auto es erwartet)."""
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime or not mime.startswith("image/"):
        # Best-effort: PNG als Default, AI-Auto akzeptiert jpg/png/webp.
        mime = "image/png"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _sync_image_bytes_from_response(payload: dict[str, Any]) -> bytes | None:
    """Manche AI-Auto Bildmodelle liefern das Bild direkt im Initial-Response
    (z.B. imagen-3 / gpt-image-1 via b64_json). Defensiv pruefen."""
    candidates: list[dict[str, Any]] = []
    g = payload.get("generation")
    if isinstance(g, dict):
        candidates.append(g)
    candidates.append(payload)
    for c in candidates:
        b64 = c.get("b64_json") or c.get("image_b64")
        if b64:
            return base64.b64decode(b64)
    return None


async def _fetch_image_with_polling(
    client: httpx.AsyncClient, generation_id: str
) -> bytes:
    """Pollt /generations/{id}/image bis ein Bild zurueckkommt oder der Job
    failed. Bei 4xx wird zusaetzlich /generations/{id} geprueft, um echte
    Fehler von 'noch nicht fertig' zu unterscheiden."""
    base = settings.aiauto_base_url
    image_url = f"{base}/generations/{generation_id}/image"
    status_url = f"{base}/generations/{generation_id}"

    deadline = asyncio.get_event_loop().time() + AIAUTO_POLL_TIMEOUT_S
    last_status: str | None = None

    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise AIAutoError(
                f"AI-Auto generation {generation_id} timed out "
                f"after {AIAUTO_POLL_TIMEOUT_S}s (last status: {last_status})"
            )

        # 1) Status-Endpoint pruefen - wenn failed, sofort abbrechen.
        status_resp = await client.get(status_url, headers=_headers())
        if status_resp.status_code == 200:
            data = status_resp.json()
            g = data.get("generation") if isinstance(data.get("generation"), dict) else data
            last_status = str(g.get("status", "")).lower()
            if last_status in ("failed", "error", "cancelled"):
                raise AIAutoError(
                    f"AI-Auto generation {generation_id} failed: "
                    f"{g.get('error') or g.get('error_message') or g}"
                )
            # Einige Bildmodelle legen fertige b64 direkt hier ab.
            sync_bytes = _sync_image_bytes_from_response(data)
            if sync_bytes:
                return sync_bytes

        # 2) Image-Endpoint pruefen
        img_resp = await client.get(image_url, headers=_headers())
        if img_resp.status_code == 200:
            ct = img_resp.headers.get("content-type", "")
            if ct.startswith("image/"):
                return img_resp.content
        elif img_resp.status_code in (401, 403):
            raise AIAutoError(
                f"AI-Auto auth error {img_resp.status_code} on image fetch: "
                f"{img_resp.text[:200]}"
            )

        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)


async def generate_image(
    prompt: str,
    output_path: Path,
    reference_images: list[Path] | None = None,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str | None = None,
) -> Path:
    """Generiert ein Bild via AI-Auto Nano Banana Pro und schreibt es nach
    output_path (PNG oder JPEG je nach Response)."""
    refs_data_urls = [
        _encode_reference_as_data_url(p)
        for p in (reference_images or [])
        if p.exists()
    ]
    if len(refs_data_urls) > 10:
        raise AIAutoError(
            f"AI-Auto erlaubt maximal 10 Reference-Images, bekommen: {len(refs_data_urls)}"
        )

    body: dict[str, Any] = {
        "prompt": prompt,
        "mode": "images",
        "model": "standard",
        "image_model": settings.aiauto_image_model,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution or settings.aiauto_image_resolution,
    }
    if refs_data_urls:
        body["i2v_reference_images"] = refs_data_urls

    url = f"{settings.aiauto_base_url}/generate"

    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url, headers=_headers(), json=body)
            if resp.status_code >= 400:
                raise AIAutoError(
                    f"AI-Auto POST /generate {resp.status_code}: {resp.text[:500]}"
                )
            payload = resp.json()

            # Einige Modelle liefern das Bild direkt synchron (b64_json) -
            # defensiv pruefen bevor wir pollen.
            sync_bytes = _sync_image_bytes_from_response(payload)
            if sync_bytes:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(sync_bytes)
                return output_path

            generation = payload.get("generation") or {}
            generation_id = generation.get("id") or payload.get("id")
            if not generation_id:
                raise AIAutoError(
                    f"AI-Auto Response enthaelt keine generation.id: {payload!r}"
                )

            image_bytes = await _fetch_image_with_polling(client, str(generation_id))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path
