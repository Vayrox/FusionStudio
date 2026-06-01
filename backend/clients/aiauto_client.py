"""
AI-Auto Client fuer Image-Generation mit Nano Banana Pro.

Zwei Namespaces, beide noetig:
  - POST https://api.ai-auto.io/api/v2/generate
      Erzeugt eine neue Generation. v2 ist die einzige API-Surface die
      nano_banana_pro / kling_* / seedance_2 akzeptiert.
      WICHTIG: v2-POST ist SYNCHRON - die Connection bleibt offen bis das
      Bild fertig gerendert ist. Bei nano_banana_pro dauert das oft 3-5min;
      Cloudflare vor AI-Auto's Origin cappt bei 120s mit 524. Wir muessen
      also IMMER auf den Listing-Fallback gehen.

  - GET https://api.ai-auto.io/api/saas/generations/...
      Listing / Status / Download. Funktioniert mit API-Key UND zeigt auch
      v2-Generationen (saas + v2 teilen sich die selbe DB).
      /api/v2/generations* ist Dashboard-only (403 mit "Dashboard login
      required") - fuer API-Clients nicht nutzbar.

Flow:
  1. POST v2/generate (Timeout absichtlich unter Cloudflare's 120s gesetzt
     damit wir nicht auf das 524 warten muessen)
  2. Listing-Fallback: GET saas/generations/images?limit=100 nach Prompt+Ts
  3. Status-Polling: GET saas/generations/{id} bis status=completed
  4. Download: video_url aus dem Status-Response (saas-URL) ODER
     GET saas/generations/{id}/download als Fallback
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import mimetypes
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

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
    MAX_PARALLEL_SEEDANCE_VIDEO_CALLS,
    settings,
)

log = logging.getLogger("fusion-auto.aiauto")

# v2 ist die einzige POST-Surface die neue Modelle akzeptiert. Hardcoded
# weil eng an die Request-Shape gekoppelt - settings.aiauto_base_url ist
# fuer Listing/Status (saas).
_GENERATE_URL = "https://api.ai-auto.io/api/v2/generate"

_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_AIAUTO_CALLS)
# Seedance v2 erlaubt pro Account nur 1 gleichzeitige Video-Generation -
# separate Semaphore damit Image-Pipeline weiterhin parallel laufen darf.
_VIDEO_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_SEEDANCE_VIDEO_CALLS)
# GPT Image 2.0 Package erlaubt nur 2 gleichzeitige Generationen pro Account
# (429 "Package concurrent limit reached"). Eigene Semaphore dafuer, damit
# nano_banana_pro weiterhin mit MAX_PARALLEL_AIAUTO_CALLS=4 laufen kann.
_GPT_IMAGE_SEMAPHORE = asyncio.Semaphore(2)


def _image_semaphore_for_model(model: str) -> asyncio.Semaphore:
    if "gpt_image" in (model or "").lower():
        return _GPT_IMAGE_SEMAPHORE
    return _SEMAPHORE

# Seedance v2 lehnt Prompts ueber 2000 Zeichen ab. GPT-Generation hat den
# Cap schon via System-Prompt + _enforce_seedance_char_limit eingebaut,
# aber Prompt-Overrides (User-Edits / Regenerate) koennen drueber sein -
# deshalb hier am API-Boundary nochmal final clippen.
SEEDANCE_PROMPT_MAX_CHARS = 2000


def _clip_prompt_for_seedance(prompt: str) -> str:
    text = (prompt or "").strip()
    if len(text) <= SEEDANCE_PROMPT_MAX_CHARS:
        return text
    cutoff = -1
    for sep in (". ", "! ", "? ", ".", "!", "?"):
        idx = text.rfind(sep, 0, SEEDANCE_PROMPT_MAX_CHARS)
        if idx > cutoff:
            cutoff = idx + len(sep.rstrip())
    if cutoff < SEEDANCE_PROMPT_MAX_CHARS // 2:
        cutoff = text.rfind(" ", 0, SEEDANCE_PROMPT_MAX_CHARS)
        if cutoff < 0:
            cutoff = SEEDANCE_PROMPT_MAX_CHARS
    truncated = text[:cutoff].rstrip()
    log.warning(
        "Seedance v2 prompt was %d chars (over %d) - truncated to %d chars at sentence boundary",
        len(text), SEEDANCE_PROMPT_MAX_CHARS, len(truncated),
    )
    return truncated

# Claimed-Set verhindert dass mehrere parallele Fallback-Calls
# (z.B. die 5 identischen Step-4-Variant-Prompts) alle dieselbe
# generation.id aus dem Listing greifen.
_CLAIMED_IDS: set[str] = set()
_CLAIM_LOCK = asyncio.Lock()


class AIAutoError(RuntimeError):
    pass


class AIAutoPermanentError(AIAutoError):
    """Nicht-retrybar (Auth, fehlender API-Key). Bricht Retry-Loops ab."""
    pass


def _headers() -> dict[str, str]:
    key = settings.aiauto_api_key
    if not key:
        raise AIAutoPermanentError(
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


# AI-Auto cappt reference_asset / i2v_reference_images bei 200_000 chars
# pro Eintrag. Ein 4k PNG (10+ MB raw -> 13+ MB base64) sprengt das massiv.
# Mit etwas Sicherheitsabstand gegen den Cap.
_REF_MAX_B64_CHARS = 195_000


def _encode_reference_as_data_url(image_path: Path) -> str:
    """Encodet ein Referenz-Bild als Data-URL fuer AI-Auto.

    AI-Auto hat ein hartes 200_000-Zeichen-Limit pro Referenz. Grosse
    Source-Bilder (4k PNG) muessen runter-resized/recomprimiert werden bis
    sie passen. Wir versuchen:
      1) Raw Bytes des Files -> wenn klein genug, original Format behalten
      2) Progressives JPEG-Recompress mit fallenden Aufloesungen + Qualities
    """
    raw_bytes = image_path.read_bytes()
    raw_b64 = base64.b64encode(raw_bytes).decode("ascii")
    if len(raw_b64) <= _REF_MAX_B64_CHARS:
        mime, _ = mimetypes.guess_type(str(image_path))
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        return f"data:{mime};base64,{raw_b64}"

    # Zu gross - via PIL re-encoden. JPEG weil PNG bei grossen Bildern
    # selten unter den Cap kommt (lossless).
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception as exc:
        raise AIAutoError(
            f"AI-Auto reference image konnte nicht geladen werden ({image_path.name}): {exc}"
        ) from exc

    # JPEG braucht RGB. PNG-Transparenz auf schwarzem Hintergrund flatten -
    # bewusst kein Weiss, weil schwarze Hintergrundbilder (z.B. unsere
    # signature_background.png) sonst Halos bekommen.
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        alpha = img.split()[-1]
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img.convert("RGB"), mask=alpha)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    original_w, original_h = img.size

    # Progressiv: erst grosse Aufloesung mit hoher Quality versuchen, dann
    # immer kleiner. Reihenfolge so dass Qualitaet so lange wie moeglich
    # erhalten bleibt.
    plans: list[tuple[int, int]] = [
        (max_side, q)
        for max_side in (1536, 1280, 1024, 768, 512)
        for q in (88, 80, 70, 60)
    ]

    last_attempt_info = ""
    for max_side, quality in plans:
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            scaled = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.LANCZOS,
            )
        else:
            scaled = img
        buf = io.BytesIO()
        scaled.save(buf, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = buf.getvalue()
        b64 = base64.b64encode(jpg_bytes).decode("ascii")
        last_attempt_info = (
            f"{scaled.size[0]}x{scaled.size[1]} q={quality} -> "
            f"{len(jpg_bytes)} bytes / {len(b64)} b64 chars"
        )
        if len(b64) <= _REF_MAX_B64_CHARS:
            log.info(
                "AI-Auto ref %s (orig %dx%d %d bytes) re-encoded as JPEG %s",
                image_path.name, original_w, original_h, len(raw_bytes),
                last_attempt_info,
            )
            return f"data:image/jpeg;base64,{b64}"

    # Letzter Ausweg: thumbnail. Liefert wenig Detail aber API akzeptiert.
    fallback = img.copy()
    fallback.thumbnail((384, 384), Image.LANCZOS)
    buf = io.BytesIO()
    fallback.save(buf, format="JPEG", quality=55, optimize=True)
    jpg_bytes = buf.getvalue()
    b64 = base64.b64encode(jpg_bytes).decode("ascii")
    log.warning(
        "AI-Auto ref %s konnte nicht in regulaere Plans (%s) gefittet werden - "
        "Fallback auf %dx%d q=55 -> %d b64 chars",
        image_path.name, last_attempt_info,
        fallback.size[0], fallback.size[1], len(b64),
    )
    return f"data:image/jpeg;base64,{b64}"


def _composite_refs_for_single_slot(refs: list[Path]) -> Path:
    """Bauen N>=2 Reference-Bilder zu einem side-by-side Composite zusammen.

    GPT Image 2.0 unterstuetzt nur einen einzigen `reference_asset`-String.
    Statt N-1 Refs zu droppen (-> Modell hat keine Pokemon-Anker fuer Step 3/4
    -> 500 "Generation failed") legen wir alle Refs in einem horizontalen
    Grid auf schwarzem Hintergrund nebeneinander. Schwarzer Background damit
    es zu signature_background.png passt (das ist auch schwarz).

    Tile-Hoehe = 1024px (genug Detail), proportionale Breite. Final-Cap
    bei 4096px Gesamt-Breite damit der b64-Cap im encode-Helper greift.
    """
    tile_h = 1024
    max_total_w = 4096
    tiles: list[Image.Image] = []
    for p in refs:
        with Image.open(p) as src:
            src.load()
            img = src.convert("RGB")
        scale = tile_h / img.height
        new_w = max(1, int(round(img.width * scale)))
        tiles.append(img.resize((new_w, tile_h), Image.LANCZOS))

    total_w = sum(t.width for t in tiles)
    if total_w > max_total_w:
        # Gleichmaessig downscalen damit Total <= max_total_w.
        shrink = max_total_w / total_w
        tile_h = max(1, int(round(tile_h * shrink)))
        new_tiles: list[Image.Image] = []
        for t in tiles:
            new_w = max(1, int(round(t.width * shrink)))
            new_tiles.append(t.resize((new_w, tile_h), Image.LANCZOS))
        tiles = new_tiles
        total_w = sum(t.width for t in tiles)

    canvas = Image.new("RGB", (total_w, tile_h), (0, 0, 0))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, 0))
        x += t.width

    fd, tmp_name = tempfile.mkstemp(suffix=".jpg", prefix="fusion_ref_composite_")
    os.close(fd)
    out_path = Path(tmp_name)
    canvas.save(out_path, format="JPEG", quality=92, optimize=True)
    return out_path


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


# Sammelt alle plausiblen URL-Felder aus einem v2 Status-/POST-Response.
# AI-Auto liefert je nach Modell unterschiedliche Shapes (output_url,
# result_url, assets[].url, generation.url, ...). Wir scannen breit damit
# wir nicht bei jeder Schema-Aenderung haengen.
_IMAGE_URL_KEYS = (
    # saas-spezifisch: `video_url` ist trotz Namen auch fuer Bilder die
    # Download-URL. `thumb_url` als Notfall-Fallback (kleinere Aufloesung).
    "video_url", "thumb_url",
    "image_url", "output_url", "result_url", "asset_url",
    "download_url", "url", "uri", "src",
)
_IMAGE_URL_LIST_KEYS = ("assets", "outputs", "results", "images", "files")


def _extract_image_urls_from_response(payload: dict[str, Any]) -> list[str]:
    """Findet alle HTTP(S)-URLs in einer Generation-Response."""
    urls: list[str] = []

    def _maybe_add(val: Any) -> None:
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            if val not in urls:
                urls.append(val)

    def _scan(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for k in _IMAGE_URL_KEYS:
                _maybe_add(node.get(k))
            for k in _IMAGE_URL_LIST_KEYS:
                v = node.get(k)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            _maybe_add(item)
                        else:
                            _scan(item, depth + 1)
            # generischer Sweep ueber alle Felder, falls AI-Auto andere Key-
            # Namen verwendet als oben gelistet
            for v in node.values():
                if isinstance(v, str):
                    _maybe_add(v)
                elif isinstance(v, (dict, list)):
                    _scan(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _scan(item, depth + 1)

    _scan(payload)
    return urls


_COMPLETED_TOKENS = ("complete", "succeed", "finish", "ready", "done", "available")
_FAILED_TOKENS = ("fail", "error", "cancel", "rejected", "timeout")


def _status_class(status: str) -> str:
    """Kategorisiert einen v2-Status. Akzeptiert auch Variationen wie
    `image_completed` oder `finished` ohne hardcoded Liste."""
    s = (status or "").lower().strip()
    if not s:
        return "unknown"
    if any(tok in s for tok in _FAILED_TOKENS):
        return "failed"
    if any(tok in s for tok in _COMPLETED_TOKENS):
        return "completed"
    return "pending"


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
    """Sucht die frisch gestartete Generation im User-Listing (saas)."""
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
    # Progressive Fallbacks: strikt -> locker. WICHTIG: 80 ist die untere
    # Grenze - damit wir bei Realistic-Single-Prompts (Format: "A full-body
    # macro image of {POKEMON} reimagined as...") den Pokemon-Namen IMMER
    # im Discriminator haben. Bei 40 oder 25 Chars matcht nur noch der
    # generische Praefix, was parallele Pokemon-Renders cross-claimen und
    # Bytes ins falsche Output-Folder kippen kann.
    match_lens = [180, 120, 80]
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
                        # v2-Listings haben 'type' (image/video). Alte saas-Listings
                        # 'mode' (images/shorts). Beides als Image-Match akzeptieren,
                        # aber Video-Generationen mit gleichem Prompt-Prefix ausschliessen.
                        gtype = (g.get("type") or g.get("mode") or "").lower()
                        if gtype and gtype not in ("image", "images"):
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


async def _try_download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Versucht eine URL und gibt image-bytes zurueck wenn content-type stimmt."""
    try:
        dl = await client.get(url, headers=_headers(), follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("AI-Auto fetch %s failed: %s", url, exc)
        return None
    if dl.status_code != 200:
        return None
    ct = (dl.headers.get("content-type") or "").lower()
    if ct.startswith("image/"):
        return dl.content
    # Manche CDNs liefern application/octet-stream - akzeptieren wenn
    # die Bytes nach einem Bild aussehen (PNG/JPEG/WebP magic).
    body = dl.content
    if body[:8] == b"\x89PNG\r\n\x1a\n" or body[:3] == b"\xff\xd8\xff" or body[:4] == b"RIFF":
        return body
    return None


def _build_download_candidates(
    base: str, generation_id: str, g: dict[str, Any]
) -> list[tuple[str, str]]:
    """Liefert (Label, URL) in der Reihenfolge die wir versuchen. video_url
    aus dem saas-Response ist die kanonische Full-Res-Quelle - thumb_url
    bewusst NICHT, weil das nur den Vorschau-Thumb liefert."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(label: str, val: Any) -> None:
        if not isinstance(val, str):
            return
        if not val.startswith(("http://", "https://")):
            return
        if val in seen:
            return
        seen.add(val)
        out.append((label, val))

    # saas-spezifisch: explizite Felder zuerst (Full-Res)
    _add("response.video_url", g.get("video_url"))
    _add("response.image_url", g.get("image_url"))
    _add("response.output_url", g.get("output_url"))
    _add("response.result_url", g.get("result_url"))
    _add("response.download_url", g.get("download_url"))
    # Konstruierte Fallbacks (sollten dieselbe URL sein wie video_url)
    _add("constructed /download", f"{base}/generations/{generation_id}/download")
    _add("constructed /image", f"{base}/generations/{generation_id}/image")
    # Thumb als ALLERLETZTE Notbremse - liefert Low-Res aber besser als nichts
    _add("response.thumb_url", g.get("thumb_url"))
    return out


async def _fetch_image_with_polling(
    client: httpx.AsyncClient, generation_id: str
) -> bytes:
    base = settings.aiauto_base_url
    status_url = f"{base}/generations/{generation_id}"

    deadline = asyncio.get_event_loop().time() + AIAUTO_POLL_TIMEOUT_S
    start_ts = asyncio.get_event_loop().time()
    last_status: str | None = None
    logged_first_response = False
    last_pending_log = 0.0

    while True:
        now = asyncio.get_event_loop().time()
        if now > deadline:
            raise AIAutoError(
                f"AI-Auto generation {generation_id} timed out "
                f"after {AIAUTO_POLL_TIMEOUT_S}s (last status: {last_status!r})"
            )

        status_resp = await client.get(status_url, headers=_headers())
        if status_resp.status_code in (401, 403):
            raise AIAutoPermanentError(
                f"AI-Auto auth error {status_resp.status_code} on status: "
                f"{status_resp.text[:200]}"
            )
        if status_resp.status_code == 200:
            try:
                data = status_resp.json()
            except Exception:
                data = {}

            if not logged_first_response:
                logged_first_response = True
                preview = status_resp.text[:600].replace("\n", " ")
                log.info(
                    "AI-Auto status[%s] first response: %s",
                    generation_id, preview,
                )

            g = data.get("generation") if isinstance(data.get("generation"), dict) else data
            if isinstance(g, dict):
                last_status = str(g.get("status") or g.get("state") or "").lower()
                klass = _status_class(last_status)
                if klass == "failed":
                    raise AIAutoError(
                        f"AI-Auto generation {generation_id} failed "
                        f"(status={last_status!r}): "
                        f"{g.get('error') or g.get('error_message') or g}"
                    )

                # Falls die Response Bytes inline mitliefert (b64)
                sync_bytes = _sync_image_bytes_from_response(data)
                if sync_bytes:
                    log.info(
                        "AI-Auto[%s] -> %d bytes from response b64",
                        generation_id, len(sync_bytes),
                    )
                    return sync_bytes

                if klass == "completed":
                    candidates = _build_download_candidates(base, generation_id, g)
                    for label, url in candidates:
                        bytes_ = await _try_download_image(client, url)
                        if bytes_:
                            log.info(
                                "AI-Auto[%s] downloaded %d bytes via %s (%s)",
                                generation_id, len(bytes_), label, url,
                            )
                            return bytes_
                    elapsed = now - start_ts
                    if elapsed > 30 and (now - last_pending_log) > 30:
                        last_pending_log = now
                        log.warning(
                            "AI-Auto[%s] status=completed seit %.0fs aber kein "
                            "Download erfolgreich. URLs versucht: %s. "
                            "Polle weiter (CDN-Propagation?).",
                            generation_id, elapsed,
                            [u for _, u in candidates],
                        )
                elif klass == "pending":
                    elapsed = now - start_ts
                    if elapsed > 60 and (now - last_pending_log) > 30:
                        last_pending_log = now
                        log.info(
                            "AI-Auto[%s] still pending (status=%r, %.0fs elapsed)",
                            generation_id, last_status, elapsed,
                        )
                elif klass == "unknown":
                    elapsed = now - start_ts
                    if elapsed > 30 and (now - last_pending_log) > 30:
                        last_pending_log = now
                        log.warning(
                            "AI-Auto[%s] unknown status=%r seit %.0fs - "
                            "Response-Preview: %s",
                            generation_id, last_status, elapsed,
                            status_resp.text[:300].replace("\n", " "),
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

    if resp.status_code in (502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530):
        log.warning(
            "AI-Auto POST /generate transient %d - fallback to listing", resp.status_code
        )
        return None, None
    if resp.status_code in (401, 403):
        raise AIAutoPermanentError(
            f"AI-Auto Auth-Error {resp.status_code} beim Image-Generate. "
            f"Der API-Key wurde abgelehnt. Pruefe in den Settings ob der "
            f"AIAUTO_API_KEY noch gueltig ist (ggf. in https://ai-auto.io "
            f"neu generieren). Server-Antwort: {resp.text[:300]}"
        )
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


async def _generate_image_once(
    prompt: str,
    output_path: Path,
    reference_images: list[Path] | None = None,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str | None = None,
    existing_generation_id: str | None = None,
    existing_submit_ts: float | None = None,
    gen_id_holder: list[str | None] | None = None,
    submit_ts_holder: list[float | None] | None = None,
) -> Path:
    """Ein einzelner Generation-Versuch. Retry passiert in generate_image().

    Anti-Duplicate-Logic (sehr wichtig fuer Credit-Verbrauch):
      - existing_generation_id: schon eine ID? -> skip POST + listing,
        direkt zum Polling.
      - existing_submit_ts: POST war schon, aber Listing hatte die Gen
        noch nicht? -> skip POST, nur erneut listing-fallback mit dem
        ORIGINAL-submit_ts (NICHT mit time.time() - das wuerde unsere
        gerade erzeugte Generation als "zu alt" rausfiltern).
      - sonst: frischer POST.
    `gen_id_holder` / `submit_ts_holder`: mutable Listen[1], in die wir
    den State schreiben sobald wir ihn kennen. Der Caller (generate_image)
    reicht sie beim Retry weiter.
    """
    existing_refs = [p for p in (reference_images or []) if p.exists()]
    if len(existing_refs) > 10:
        raise AIAutoError(
            f"AI-Auto erlaubt maximal 10 Reference-Images, bekommen: {len(existing_refs)}"
        )

    # Model-aware ref handling:
    # GPT Image 2.0 nimmt nur EIN reference_asset entgegen. Statt N-1 refs
    # einfach zu droppen (-> 500 wenn z.B. Step 3 die zwei Pokemon-Refs verliert),
    # compositen wir mehrere Refs zu einer side-by-side Kachel zusammen, damit
    # GPT Image 2.0 alle Anchor-Pokemon "sieht".
    # WICHTIG: Die Prompts (Step 3/4) verweisen explizit auf "reference 1/2/3".
    # Bei GPT Image 2.0 zeigen wir aber nur EIN Bild (das Composite). Damit das
    # Modell die "reference N"-Verweise korrekt interpretiert, prependen wir
    # eine Panel-Legende an den Prompt die erklaert dass das Single-Ref-Bild
    # aus N nebeneinander gelegten Panels besteht.
    active_model_for_refs = settings.aiauto_image_model
    if "gpt_image" in (active_model_for_refs or "").lower() and len(existing_refs) > 1:
        composite_path = _composite_refs_for_single_slot(existing_refs)
        refs_data_urls = [_encode_reference_as_data_url(composite_path)]
        n = len(existing_refs)
        panel_legend = (
            f"REFERENCE IMAGE LEGEND: The single reference image you receive is a "
            f"horizontal composite of {n} panels placed side by side, left to right. "
            + " ".join(
                f"Panel {i+1} (from the left) = reference {i+1}."
                for i in range(n)
            )
            + " When the instructions below say 'reference 1', 'reference 2', etc, "
            "they mean the corresponding panel in this composite. Do NOT copy the "
            "side-by-side composite layout into your output - read each panel as a "
            "separate visual reference for the subject the instructions ask you to "
            "render.\n\n"
        )
        prompt = panel_legend + prompt
        log.info(
            "AI-Auto image model %r: composited %d refs into single side-by-side "
            "image + prepended panel legend to prompt.",
            active_model_for_refs, n,
        )
    else:
        refs_data_urls = [_encode_reference_as_data_url(p) for p in existing_refs]

    # POST IMMER an v2 (saas-POST kennt die neuen Modelle nicht).
    # Listing/Status/Download laufen weiter via settings.aiauto_base_url (saas).
    url = _GENERATE_URL

    # Semaphore VOR dem Acquire whaehlen - GPT Image 2.0 hat strikteren
    # Concurrent-Limit (2) als nano_banana_pro (MAX_PARALLEL_AIAUTO_CALLS=4).
    active_model = settings.aiauto_image_model
    semaphore = _image_semaphore_for_model(active_model)

    async with semaphore:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            if existing_generation_id:
                log.info(
                    "AI-Auto resume polling existing generation %s "
                    "(kein neuer POST - schont Credits)",
                    existing_generation_id,
                )
                generation_id = existing_generation_id
                sync_bytes = None
            elif existing_submit_ts is not None:
                # POST war schon erfolgreich (oder 524'd), aber listing-fallback
                # hatte die Generation beim letzten Versuch noch nicht gefunden.
                # KEIN neuer POST - nur listing erneut probieren mit dem ORIGINAL
                # submit_ts, damit der Timestamp-Filter unsere echte Gen nicht
                # als "zu alt" rausschmeisst.
                log.info(
                    "AI-Auto retry listing-fallback (kein neuer POST) "
                    "mit original submit_ts=%.0f age=%.0fs",
                    existing_submit_ts, time.time() - existing_submit_ts,
                )
                generation_id = await _find_recent_generation(
                    client, prompt, existing_submit_ts,
                )
                sync_bytes = None
            else:
                image_model = active_model
                body: dict[str, Any] = {
                    "type": "image",
                    "model": image_model,
                    "prompt": prompt,
                    "ratio": aspect_ratio,
                    "quality": resolution or settings.aiauto_image_resolution,
                    "count": 1,
                }
                if refs_data_urls:
                    # Reference-Field-Name ist model-abhaengig:
                    #   - nano_banana_pro / imagen_*: i2v_reference_images (Array,
                    #     Multi-Ref Ingredients-Mode)
                    #   - gpt_image_2 + andere GPT-Image-Modelle: reference_asset
                    #     (Single-String, refs sind oben schon zu einem
                    #     Composite zusammengebaut wenn N>1)
                    body["use_image_reference"] = True
                    if "gpt_image" in image_model.lower():
                        body["reference_asset"] = refs_data_urls[0]
                    else:
                        body["i2v_reference_images"] = refs_data_urls

                submit_ts = time.time()
                # submit_ts SOFORT in den Holder schreiben, BEVOR der POST losgeht.
                # Falls AI-Auto die Gen serverseitig anlegt aber dann mit 4xx /
                # Network-Error aus dem POST-Aufruf rauskracht, koennen wir bei
                # der naechsten Retry trotzdem listing-faller mit dem ORIGINAL
                # submit_ts und finden die Gen.
                if submit_ts_holder is not None:
                    submit_ts_holder[0] = submit_ts
                sync_bytes, generation_id = await _post_generate(client, url, body)

                if sync_bytes is None and generation_id is None:
                    # POST timed out / 524 -> Generation laeuft serverseitig
                    # weiter. submit_ts JETZT persistieren (NICHT vorher), damit
                    # ein nachfolgender 4xx-Reject NICHT versehentlich den
                    # retry-skip-POST-Pfad triggert. Listing-fallback raises
                    # bei Miss, der Retry uebernimmt dann via existing_submit_ts.
                    if submit_ts_holder is not None:
                        submit_ts_holder[0] = submit_ts
                    generation_id = await _find_recent_generation(
                        client, prompt, submit_ts,
                    )
                elif generation_id is not None and submit_ts_holder is not None:
                    # Fast-path: POST hat direkt eine gen_id geliefert (selten,
                    # nur bei wirklich schnellen Models). submit_ts trotzdem
                    # persistieren als zusaetzlicher Schutz.
                    submit_ts_holder[0] = submit_ts

            # gen_id merken bevor wir pollen, damit ein spaeterer Fehler
            # den outer retry NICHT erneut listet/POSTet.
            if gen_id_holder is not None and generation_id:
                gen_id_holder[0] = generation_id

            if sync_bytes is None:
                assert generation_id is not None
                sync_bytes = await _fetch_image_with_polling(client, generation_id)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(sync_bytes)
        return output_path


async def generate_image(
    prompt: str,
    output_path: Path,
    reference_images: list[Path] | None = None,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str | None = None,
) -> Path:
    """Generiert ein Bild via AI-Auto. Retried unendlich bei transienten
    Fehlern (Timeout, 5xx, "failed" status, listing-miss). Permanente Fehler
    (Auth, fehlender API-Key) brechen sofort ab.

    WICHTIG fuer Credit-Verbrauch: sobald wir einmal gePOSTet haben (und
    damit AI-Auto-seitig eine Generation erzeugt wurde), bleibt der
    submit_ts ueber alle Retries hinweg derselbe. Selbst wenn der Listing-
    Fallback beim ersten Versuch die Gen nicht findet, retried der Loop
    nur das Listing - er macht KEINEN neuen POST. So entstehen pro
    generate_image()-Call maximal 1 AI-Auto-Generation, egal wie oft
    intern retried wird.
    """
    attempt = 0
    backoff = 5.0
    max_backoff = 60.0
    prompt_hint = (prompt or "")[:60]
    gen_id_holder: list[str | None] = [None]
    submit_ts_holder: list[float | None] = [None]
    while True:
        attempt += 1
        try:
            return await _generate_image_once(
                prompt, output_path,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                existing_generation_id=gen_id_holder[0],
                existing_submit_ts=submit_ts_holder[0],
                gen_id_holder=gen_id_holder,
                submit_ts_holder=submit_ts_holder,
            )
        except AIAutoPermanentError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "AI-Auto generate_image attempt %d failed (%s: %s) - retry in %.0fs "
                "[prompt-prefix=%r out=%s gen_id=%s submit_ts=%s]",
                attempt, type(exc).__name__, exc, backoff,
                prompt_hint, output_path.name,
                gen_id_holder[0], submit_ts_holder[0],
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


# ---------------------------------------------------------------------------
# Video-Generation (Seedance 2 via AI-Auto)
# ---------------------------------------------------------------------------


async def _find_recent_video_generation(
    client: httpx.AsyncClient,
    prompt: str,
    submit_ts: float,
) -> str | None:
    """Findet die frisch gestartete Video-Generation im Listing.

    Analog zu _find_recent_generation fuer Bilder - aber:
      - probiert MEHRERE Endpoint-Varianten (saas hat ein video-spezifisches
        Listing, aber AI-Auto hat das schon mehrfach umbenannt)
      - der Type-Filter ist permissiv: alles AUSSER 'image' / 'images' wird
        als Video-Kandidat akzeptiert (also v2's 'type=video' aber auch
        'seedance', 'kling', 'shorts', 'longform' und Neue die wir nicht
        kennen)
      - logt bei Exhaustion ein Sample der gesehenen Items + raw Response-
        Previews, damit man im Server-Log direkt erkennt was AI-Auto
        tatsaechlich liefert."""
    base = settings.aiauto_video_base_url
    list_urls = [
        f"{base}/generations/videos?limit=100",
        f"{base}/generations/shorts?limit=100",
        f"{base}/generations?limit=100",
    ]
    prompt_prefix = (prompt or "")[:220].strip()
    if not prompt_prefix:
        return None

    def _normalize(s: str) -> str:
        return " ".join((s or "").split()).lower()

    want_full = _normalize(prompt_prefix)
    # Untere Grenze 80 Chars (analog zum Image-Pfad) - sonst koennen
    # parallele Video-Generations mit aehnlichem Prompt-Anfang cross-matchen.
    match_lens = [180, 120, 80]
    last_samples: list[dict[str, Any]] = []
    last_raw_previews: list[str] = []

    log.warning(
        "AI-Auto video fallback START: want-prefix=%r submit_ts=%.0f",
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
                        "AI-Auto video GET %s -> %d: %s",
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
                    for key in ("generations", "videos", "shorts", "results", "data", "items"):
                        v = data.get(key)
                        if isinstance(v, list):
                            items = v
                            break

                src = list_url.rsplit("/", 1)[-1].split("?")[0]
                preview = raw_text[:250].replace("\n", " ")
                last_raw_previews.append(
                    f"[{src}] attempt={attempt+1} items={len(items)} "
                    f"top-level-keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__} "
                    f"raw={preview!r}"
                )
                last_raw_previews = last_raw_previews[-3:]

                if items:
                    last_samples = [
                        {
                            "id": g.get("id") if isinstance(g, dict) else None,
                            "type": g.get("type") if isinstance(g, dict) else None,
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
                        # Permissive type filter: alles AUSSER explizit Bild-Typ
                        # als Video-Kandidat behandeln. Neue AI-Auto type-Werte
                        # ('seedance', 'kling', 'v2_video', ...) werden dadurch
                        # nicht versehentlich rausgefiltert.
                        gtype = (g.get("type") or g.get("mode") or "").lower()
                        if gtype in ("image", "images"):
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
                                "AI-Auto video fallback CLAIM: id=%s prefix=%d source=%s "
                                "(attempt %d, candidates=%d)",
                                gen_id, match_len, src, attempt + 1, len(candidates),
                            )
                            return gen_id
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "AI-Auto video listing %s attempt %d failed: %s",
                    list_url, attempt + 1, exc,
                )
        await asyncio.sleep(AIAUTO_POLL_INTERVAL_S)

    sample_repr = "\n".join(
        f"  - [{s['source']}] id={s['id']} type={s['type']!r} mode={s['mode']!r} "
        f"status={s['status']!r} created={s['created_at']!r} prompt={s['prompt_prefix']!r}"
        for s in last_samples
    ) or "  (listing was empty)"
    raw_repr = "\n".join(f"  {p}" for p in last_raw_previews) or "  (no raw responses)"
    log.warning(
        "AI-Auto video listing fallback EXHAUSTED %d attempts. want-prefix=%r\n"
        "Samples:\n%s\nLast raw:\n%s",
        AIAUTO_LIST_MATCH_ATTEMPTS, want_full[:40], sample_repr, raw_repr,
    )
    return None


async def _poll_and_download_video(
    client: httpx.AsyncClient, generation_id: str
) -> bytes:
    """Pollt /generations/{id} bis status=completed, dann GET /download als mp4.
    Nutzt den Seedance v2-Endpoint."""
    base = settings.aiauto_video_base_url
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
    resolution: str | None = None,
    seconds: int | None = None,
    model: str | None = None,
) -> Path:
    """Generiert ein Seedance-2 Video via AI-Auto v2-Endpoint und schreibt
    es als mp4 nach output_path.

    Refs werden als reference_asset (Data-URLs) eingebunden. Entweder
    `reference_image` (single) ODER `reference_images` (multi, z.B. fuer
    Start-Frame + End-Frame Morphs). `reference_images` hat Vorrang.

    `resolution`, `seconds`, `model`: None -> Defaults aus Settings
    (AIAUTO_VIDEO_QUALITY=4k, AIAUTO_VIDEO_DURATION=15, AIAUTO_VIDEO_MODEL).
    """
    quality = resolution or settings.aiauto_video_quality
    duration = seconds if seconds is not None else settings.aiauto_video_duration
    video_model = model or settings.aiauto_video_model
    # Final-Clip am API-Boundary - faengt User-Edits / Overrides ab.
    prompt = _clip_prompt_for_seedance(prompt)

    body: dict[str, Any] = {
        "type": "video",
        "model": video_model,
        "prompt": prompt,
        "ratio": aspect_ratio,
        "quality": quality,
        "duration": duration,
        "count": 1,
    }
    refs: list[Path] = []
    if reference_images:
        refs = [p for p in reference_images if p and p.exists()]
    elif reference_image and reference_image.exists():
        refs = [reference_image]
    if refs:
        encoded = [_encode_reference_as_data_url(p) for p in refs]
        # AI-Auto's v2 video-Endpoint akzeptiert reference_asset NUR als
        # einzelnen String - sowohl fuer Seedance als auch fuer Kling
        # (verifiziert via 422 'Input should be a valid string' bei beiden).
        # Multi-Ref / First-Last-Frame wird ueber die API nicht unterstuetzt.
        # Wir nehmen daher immer die ERSTE Ref (= bei Step 5 das start_frame,
        # was als Animation-Anchor passt - End-State beschreibt der Prompt).
        body["reference_asset"] = encoded[0]
        if len(encoded) > 1:
            log.warning(
                "AI-Auto video model %r: API supports only single reference_asset, "
                "drop %d additional refs (used: first one - in step 5 that's the "
                "start_frame; end-state must be described in the prompt).",
                video_model, len(encoded) - 1,
            )
        # Kling braucht das Flag explizit; Seedance ignoriert unbekannte Felder,
        # also schadet das Setzen bei beiden Modellen nicht.
        body["use_image_reference"] = True

    # POST IMMER an v2 (saas-POST kennt seedance_2 / kling_* nicht).
    # Listing/Status/Download laufen weiter via settings.aiauto_video_base_url (saas).
    url = _GENERATE_URL
    submit_ts = time.time()

    async with _VIDEO_SEMAPHORE:
        async with httpx.AsyncClient(timeout=AIAUTO_REQUEST_TIMEOUT_S) as client:
            generation_id: str | None = None
            try:
                resp = await client.post(
                    url, headers=_headers(), json=body, timeout=AIAUTO_POST_TIMEOUT_S,
                )
                if resp.status_code in (502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530):
                    log.warning(
                        "AI-Auto POST /generate (video) transient %d - fallback to listing",
                        resp.status_code,
                    )
                elif resp.status_code in (401, 403):
                    raise AIAutoError(
                        f"AI-Auto Auth-Error {resp.status_code} beim Video-Generate. "
                        f"Der API-Key wurde abgelehnt. Pruefe in den Settings: "
                        f"(1) ist der AIAUTO_API_KEY noch gueltig? "
                        f"(2) hat dein Account Seedance-Zugriff? "
                        f"(3) muss der Key in https://ai-auto.io neu generiert werden? "
                        f"Server-Antwort: {resp.text[:300]}"
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
                        "die Generation wurde auch nicht im Listing gefunden. "
                        "Mehr Details im Server-Terminal: such nach 'AI-Auto video "
                        "listing fallback EXHAUSTED' - der Log zeigt Sample-Items "
                        "die AI-Auto in der Liste zurueckgibt und die letzten Raw-"
                        "Responses, damit man sieht ob (1) das Listing leer ist, "
                        "(2) die Items einen unbekannten 'type' haben oder (3) "
                        "der prompt-prefix in keiner Generation matcht."
                    )

            video_bytes = await _poll_and_download_video(client, str(generation_id))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)
        return output_path
