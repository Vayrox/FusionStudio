"""
AI-Auto Client fuer Image-Generation mit Nano Banana Pro.

Robust gegen 524/Timeout: AI-Auto haelt bei einigen Modellen die HTTP-
Verbindung offen waehrend das Bild rendert; Cloudflare vor ihrem Origin
kappt bei 120s mit Cloudflare-524. Der Job laeuft trotzdem durch, die
Generation erscheint in /generations. Wenn POST /generate timeouted,
suchen wir die Generation via GET /generations ueber Prompt + Timestamp
und pollen dann /generations/{id}/image wie im Normalfall.

Basiert auf der offiziellen AI-Auto SaaS-Doc:
  Base URL: https://api.ai-auto.io/api/saas
  POST /generate
  GET  /generations                    - listing
  GET  /generations/{id}/image         - fertiges Bild (JPEG)
  GET  /generations/{id}               - Status (optional)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import (
    AIAUTO_LIST_MATCH_ATTEMPTS,
    AIAUTO_LIST_MATCH_TOLERANCE_S,
    AIAUTO_POLL_INTERVAL_S,
    AIAUTO_POLL_TIMEOUT_S,
    AIAUTO_POST_TIMEOUT_S,
    AIAUTO_REQUEST_TIMEOUT_S,
    AIAUTO_VIDEO_POLL_TIMEOUT_S,
    DEFAULT_ASPECT_RATIO,
    MAX_PARALLEL_AIAUTO_CALLS,
    settings,
)

log = logging.getLogger("fusion-auto.aiauto")

_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_AIAUTO_CALLS)

# Claimed-Set verhindert dass mehrere parallele Fallback-Calls
# (z.B. die 5 identischen Step-4-Variant-Prompts) alle dieselbe
# generation.id aus dem Listing greifen.
_CLAIMED_IDS: set[str] = set()
_CLAIM_LOCK = asyncio.Lock()


class AIAutoError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    key = settings.aiauto_api_key
    if not key:
        raise AIAutoError(
            "AIAUTO_API_KEY ist nicht gesetzt. Im Dashboard unter Settings eintragen."
        )
    # AI-Auto akzeptiert beide Auth-Header. Image-API nutzt 'Authorization: Bearer',
    # Video-/Seedance-API nutzt 'X-API-Key'. Wir senden beide damit beide Wege gehen.
    return {
        "Authorization": f"Bearer {key}",
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _encode_reference_as_data_url(image_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _sync_image_bytes_from_response(payload: dict[str, Any]) -> bytes | None:
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


def _parse_iso_ts(raw: str) -> float | None:
    """Parsed einen ISO-Timestamp zu Unix-Sekunden.

    Wichtig: AI-Auto liefert created_at oft OHNE Timezone-Suffix
    (z.B. '2026-04-24T01:45:21.736871'). datetime.fromisoformat erzeugt
    dann ein naives datetime, dessen .timestamp() die lokale Zone annimmt
    und bei UTC+2 falsche Werte liefert. Wir treat'en naive Timestamps
    deshalb explizit als UTC.
    """
    if not raw:
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def _find_recent_generation(
    client: httpx.AsyncClient,
    prompt: str,
    submit_ts: float,
) -> str | None:
    """Sucht die frisch gestartete Generation im User-Listing."""
    list_urls = [
        f"{settings.aiauto_base_url}/generations/images?limit=100",
        f"{settings.aiauto_base_url}/generations?limit=100",
    ]
    # Laenge bewusst grosszuegig: der Step-4-Prompt beginnt bei ALLEN Fusionen
    # mit 'Create a new Pokemon specimen - a fusion between ...' (49 Chars),
    # die Pokemon-Namen kommen erst danach. Zu kurze Prefixes matchen quer
    # ueber Fusionen.
    prompt_prefix = (prompt or "")[:220].strip()
    if not prompt_prefix:
        return None

    def _normalize(s: str) -> str:
        return " ".join((s or "").split()).lower()

    want_full = _normalize(prompt_prefix)
    # Progressive Fallbacks: strikt -> locker. 180 Chars deckt garantiert
    # die Pokemon-Namen + einige Descriptor-Woerter ab, sodass parallele
    # Batch-Fusionen nicht cross-contaminieren.
    match_lens = [180, 120, 80, 40, 25]
    last_samples: list[dict[str, Any]] = []
    last_raw_previews: list[str] = []

    log.warning(
        "AI-Auto fallback START: want-prefix=%r submit_ts=%.0f",
        want_full[:40], submit_ts,
    )

    for attempt in range(AIAUTO_LIST_MATCH_ATTEMPTS):
        for list_url in list_urls:
            try:
                resp = await client.get(list_url, headers=_headers())
                if resp.status_code == 404:
                    continue
                if resp.status_code != 200:
                    log.warning(
                        "AI-Auto GET %s -> %d: %s",
                        list_url, resp.status_code, resp.text[:200],
                    )
                    continue
                raw_text = resp.text
                try:
                    data = resp.json()
                except Exception:
                    data = None

                # Items aus verschiedenen moeglichen Shapes extrahieren
                items: list[Any] = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    for key in ("generations", "images", "results", "data", "items"):
                        v = data.get(key)
                        if isinstance(v, list):
                            items = v
                            break

                # Raw-Preview des Responses merken
                src = list_url.rsplit("/", 1)[-1].split("?")[0]
                preview = raw_text[:250].replace("\n", " ")
                last_raw_previews.append(
                    f"[{src}] attempt={attempt+1} items={len(items)} "
                    f"top-level-keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__} "
                    f"raw={preview!r}"
                )
                # Nur die letzten 3 Previews behalten
                last_raw_previews = last_raw_previews[-3:]

                if items:
                    last_samples = [
                        {
                            "id": g.get("id") if isinstance(g, dict) else None,
                            "mode": g.get("mode") if isinstance(g, dict) else None,
                            "status": g.get("status") if isinstance(g, dict) else None,
                            "created_at": g.get("created_at") if isinstance(g, dict) else None,
                            "prompt_prefix": (g.get("prompt") or "")[:80] if isinstance(g, dict) else "",
                            "source": src,
                        }
                        for g in items[:5]
                    ]

                for match_len in match_lens:
                    needle = want_full[:match_len]
                    if len(needle) < 6:
                        continue
                    candidates: list[tuple[str, float]] = []
                    for g in items:
                        if not isinstance(g, dict):
                            continue
                        g_prompt_norm = _normalize(g.get("prompt") or "")
                        if not g_prompt_norm:
                            continue
                        if not (g_prompt_norm.startswith(needle) or needle in g_prompt_norm[:200]):
                            continue
                        ts = _parse_iso_ts(str(g.get("created_at", "")))
                        if ts is not None and ts + AIAUTO_LIST_MATCH_TOLERANCE_S < submit_ts:
                            continue
                        gen_id = g.get("id")
                        if gen_id:
                            candidates.append((str(gen_id), ts if ts is not None else 0.0))
                    if not candidates:
                        continue
                    # Bevorzuge Kandidaten zeitlich nah am submit_ts
                    candidates.sort(key=lambda c: abs(c[1] - submit_ts) if c[1] else 1e9)
                    async with _CLAIM_LOCK:
                        for gen_id, _ts in candidates:
                            if gen_id in _CLAIMED_IDS:
                                continue
                            _CLAIMED_IDS.add(gen_id)
                            log.warning(
                                "AI-Auto fallback CLAIM: id=%s prefix=%d source=%s "
                                "(candidates=%d already-claimed=%d)",
                                gen_id, match_len, src, len(candidates),
                                sum(1 for c, _ in candidates if c in _CLAIMED_IDS) - 1,
                            )
                            return gen_id
            except Exception as exc:  # noqa: BLE001
                log.warning("AI-Auto listing %s attempt %d failed: %s",
                            list_url, attempt + 1, exc)
        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)

    sample_repr = "\n".join(
        f"  - [{s['source']}] id={s['id']} mode={s['mode']!r} status={s['status']!r} "
        f"created={s['created_at']!r} prompt={s['prompt_prefix']!r}"
        for s in last_samples
    ) or "  (listing was empty)"
    raw_repr = "\n".join(f"  {p}" for p in last_raw_previews) or "  (no raw responses)"
    log.warning(
        "AI-Auto listing fallback EXHAUSTED %d attempts. want-prefix=%r\nSamples:\n%s\nLast raw:\n%s",
        AIAUTO_LIST_MATCH_ATTEMPTS, want_full[:40], sample_repr, raw_repr,
    )
    raise AIAutoError(
        "AI-Auto POST /generate hat nicht geantwortet und die Generation "
        "wurde auch nicht im Listing gefunden.\n"
        f"Gesuchter Prompt-Prefix: {want_full[:60]!r}\n"
        f"Zuletzt gesehene Generations:\n{sample_repr}\n"
        f"Letzte Raw-Responses:\n{raw_repr}"
    )


async def _fetch_image_with_polling(
    client: httpx.AsyncClient, generation_id: str
) -> bytes:
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

        status_resp = await client.get(status_url, headers=_headers())
        if status_resp.status_code == 200:
            try:
                data = status_resp.json()
            except Exception:
                data = {}
            g = data.get("generation") if isinstance(data.get("generation"), dict) else data
            if isinstance(g, dict):
                last_status = str(g.get("status", "")).lower()
                if last_status in ("failed", "error", "cancelled"):
                    raise AIAutoError(
                        f"AI-Auto generation {generation_id} failed: "
                        f"{g.get('error') or g.get('error_message') or g}"
                    )
                sync_bytes = _sync_image_bytes_from_response(data)
                if sync_bytes:
                    return sync_bytes

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


async def _post_generate(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
) -> tuple[bytes | None, str | None]:
    """Versucht den POST. Gibt (sync_bytes, generation_id) zurueck.

    Bei Timeout/524/502/503/504 wird (None, None) zurueckgegeben - der
    Aufrufer faellt dann auf Listing-Polling zurueck.
    """
    try:
        resp = await client.post(
            url, headers=_headers(), json=body, timeout=AIAUTO_POST_TIMEOUT_S,
        )
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError) as exc:
        log.warning("AI-Auto POST /generate network timeout: %s - fallback to listing", exc)
        return None, None

    if resp.status_code in (502, 503, 504, 524):
        log.warning(
            "AI-Auto POST /generate transient %d - fallback to listing", resp.status_code
        )
        return None, None
    if resp.status_code >= 400:
        raise AIAutoError(
            f"AI-Auto POST /generate {resp.status_code}: {resp.text[:500]}"
        )

    try:
        payload = resp.json()
    except Exception as exc:
        raise AIAutoError(f"AI-Auto POST /generate invalid JSON: {exc}") from exc

    sync_bytes = _sync_image_bytes_from_response(payload)
    if sync_bytes:
        return sync_bytes, None

    gen = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    generation_id = gen.get("id") or payload.get("id")
    if not generation_id:
        raise AIAutoError(
            f"AI-Auto Response enthaelt keine generation.id: {payload!r}"
        )
    return None, str(generation_id)


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
    submit_ts = time.time()

    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            sync_bytes, generation_id = await _post_generate(client, url, body)

            if sync_bytes is None and generation_id is None:
                # POST timed out / 524 - listing-fallback (raised AIAutoError bei Miss)
                generation_id = await _find_recent_generation(client, prompt, submit_ts)

            if sync_bytes is None:
                assert generation_id is not None
                sync_bytes = await _fetch_image_with_polling(client, generation_id)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(sync_bytes)
        return output_path


# ---------------------------------------------------------------------------
# Video-Generation (Seedance 2 via AI-Auto)
# ---------------------------------------------------------------------------


async def _find_recent_video_generation(
    client: httpx.AsyncClient,
    prompt: str,
    submit_ts: float,
) -> str | None:
    """Findet die frisch gestartete Video-Generation im Listing (analog
    zu image-listing, aber mode='shorts' / model='seedance_2')."""
    list_urls = [
        f"{settings.aiauto_base_url}/generations?limit=100",
    ]
    prompt_prefix = (prompt or "")[:220].strip()
    if not prompt_prefix:
        return None

    def _normalize(s: str) -> str:
        return " ".join((s or "").split()).lower()

    want_full = _normalize(prompt_prefix)
    match_lens = [180, 120, 80, 40]

    for attempt in range(AIAUTO_LIST_MATCH_ATTEMPTS):
        for list_url in list_urls:
            try:
                resp = await client.get(list_url, headers=_headers())
                if resp.status_code != 200:
                    continue
                data = resp.json()
                items = data.get("generations", []) if isinstance(data, dict) else []
                for match_len in match_lens:
                    needle = want_full[:match_len]
                    if len(needle) < 6:
                        continue
                    candidates: list[tuple[str, float]] = []
                    for g in items:
                        if not isinstance(g, dict):
                            continue
                        mode = (g.get("mode") or "").lower()
                        if mode and mode not in ("shorts", "longform"):
                            continue
                        g_prompt = _normalize(g.get("prompt") or "")
                        if not g_prompt:
                            continue
                        if not (g_prompt.startswith(needle) or needle in g_prompt[:200]):
                            continue
                        ts = _parse_iso_ts(str(g.get("created_at", "")))
                        if ts is not None and ts + AIAUTO_LIST_MATCH_TOLERANCE_S < submit_ts:
                            continue
                        gen_id = g.get("id")
                        if gen_id:
                            candidates.append((str(gen_id), ts if ts is not None else 0.0))
                    if not candidates:
                        continue
                    candidates.sort(key=lambda c: abs(c[1] - submit_ts) if c[1] else 1e9)
                    async with _CLAIM_LOCK:
                        for gen_id, _ts in candidates:
                            if gen_id in _CLAIMED_IDS:
                                continue
                            _CLAIMED_IDS.add(gen_id)
                            log.warning(
                                "AI-Auto video fallback CLAIM: id=%s prefix=%d (attempt %d)",
                                gen_id, match_len, attempt + 1,
                            )
                            return gen_id
            except Exception as exc:  # noqa: BLE001
                log.warning("AI-Auto video listing attempt %d failed: %s", attempt + 1, exc)
        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)
    return None


async def _poll_and_download_video(
    client: httpx.AsyncClient, generation_id: str
) -> bytes:
    """Pollt /generations/{id} bis status=completed, dann GET /download als mp4."""
    base = settings.aiauto_base_url
    status_url = f"{base}/generations/{generation_id}"
    download_url = f"{base}/generations/{generation_id}/download"

    deadline = asyncio.get_event_loop().time() + AIAUTO_VIDEO_POLL_TIMEOUT_S
    last_status: str | None = None

    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise AIAutoError(
                f"AI-Auto video {generation_id} timed out after "
                f"{AIAUTO_VIDEO_POLL_TIMEOUT_S}s (last status: {last_status})"
            )

        resp = await client.get(status_url, headers=_headers())
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                data = {}
            g = data.get("generation") if isinstance(data.get("generation"), dict) else data
            if isinstance(g, dict):
                last_status = str(g.get("status", "")).lower()
                if last_status in ("completed", "succeeded", "success", "done"):
                    dl = await client.get(
                        download_url, headers=_headers(), follow_redirects=True,
                    )
                    if dl.status_code != 200:
                        raise AIAutoError(
                            f"AI-Auto video {generation_id} download {dl.status_code}: {dl.text[:200]}"
                        )
                    return dl.content
                if last_status in ("failed", "error", "cancelled"):
                    raise AIAutoError(
                        f"AI-Auto video {generation_id} {last_status}: "
                        f"{g.get('error') or g.get('error_message') or g}"
                    )
        elif resp.status_code in (401, 403):
            raise AIAutoError(
                f"AI-Auto auth error {resp.status_code} on video status: "
                f"{resp.text[:200]}"
            )

        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)


async def generate_video(
    prompt: str,
    output_path: Path,
    reference_image: Path | None = None,
    reference_images: list[Path] | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "720p",
    seconds: int = 10,
    model: str = "seedance_2",
) -> Path:
    """Generiert ein Seedance-2 Video via AI-Auto und schreibt es als mp4
    nach output_path.

    Refs werden als ingredients-mode I2V-Refs eingebunden (Data-URLs).
    Entweder `reference_image` (single) ODER `reference_images` (multi,
    z.B. fuer Start-Frame + End-Frame Morphs). `reference_images` hat
    Vorrang wenn beide gesetzt sind."""
    body: dict[str, Any] = {
        "prompt": prompt,
        "mode": "shorts",
        "model": model,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "seconds": seconds,
    }
    refs: list[Path] = []
    if reference_images:
        refs = [p for p in reference_images if p and p.exists()]
    elif reference_image and reference_image.exists():
        refs = [reference_image]
    if refs:
        body["i2v_mode"] = "ingredients"
        body["i2v_reference_images"] = [_encode_reference_as_data_url(p) for p in refs]

    url = f"{settings.aiauto_base_url}/generate"
    submit_ts = time.time()

    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            generation_id: str | None = None
            try:
                resp = await client.post(
                    url, headers=_headers(), json=body, timeout=AIAUTO_POST_TIMEOUT_S,
                )
                if resp.status_code in (502, 503, 504, 524):
                    log.warning(
                        "AI-Auto POST /generate (video) transient %d - fallback to listing",
                        resp.status_code,
                    )
                elif resp.status_code >= 400:
                    raise AIAutoError(
                        f"AI-Auto POST /generate (video) {resp.status_code}: {resp.text[:500]}"
                    )
                else:
                    payload = resp.json()
                    gen = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
                    generation_id = gen.get("id") or payload.get("id")
            except (httpx.ReadTimeout, httpx.ConnectTimeout,
                    httpx.PoolTimeout, httpx.RemoteProtocolError) as exc:
                log.warning(
                    "AI-Auto POST /generate (video) network timeout: %s - fallback to listing",
                    exc,
                )

            if not generation_id:
                generation_id = await _find_recent_video_generation(client, prompt, submit_ts)
                if not generation_id:
                    raise AIAutoError(
                        "AI-Auto POST /generate (video) hat nicht geantwortet und "
                        "die Generation wurde auch nicht im Listing gefunden."
                    )

            video_bytes = await _poll_and_download_video(client, str(generation_id))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)
        return output_path
