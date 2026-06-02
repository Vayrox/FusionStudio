"""Custom Generation - On-Demand Bild- und Video-Generation ohne Pipeline.

Erlaubt es, direkt via Dashboard:
  - Prompts zu tippen
  - Referenz-Bilder hochzuladen
  - Bilder via Nano Banana Pro / GPT Image 2.0 / etc. zu generieren
  - Videos via Seedance / Kling zu generieren

Outputs landen in OUTPUT_DIR/_custom_generation/. State wird in der
gleichen jobs.json gespeichert (top-level Liste `custom_generations`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.clients import aiauto_client
from backend.config import OUTPUT_DIR, PROJECT_ROOT, settings
from backend.pipeline import runner as pipeline_runner

log = logging.getLogger("fusion-auto.custom-gen")


CUSTOM_GEN_DIR = OUTPUT_DIR / "_custom_generation"
CUSTOM_REFS_DIR = CUSTOM_GEN_DIR / "refs"
CUSTOM_GEN_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM_REFS_DIR.mkdir(parents=True, exist_ok=True)


_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = name.strip() or "ref"
    base = _SAFE_FILENAME_RE.sub("_", base)
    return base[:80]


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


# ---------------------------------------------------------------------------
# State helpers - reuse pipeline_runner's shared STATE_FILE lock + cache.
# ---------------------------------------------------------------------------


async def _load_list() -> list[dict[str, Any]]:
    state = await pipeline_runner._load_state()
    return list(state.get("custom_generations") or [])


async def _update_entry(gen_id: str, **patch: Any) -> dict[str, Any] | None:
    async with pipeline_runner._STATE_LOCK:
        state = await pipeline_runner._load_state()
        gens = list(state.get("custom_generations") or [])
        idx = next((i for i, g in enumerate(gens) if g.get("id") == gen_id), -1)
        if idx < 0:
            return None
        entry = dict(gens[idx] or {})
        entry.update(patch)
        entry["updated_at"] = _now_iso()
        gens[idx] = entry
        state["custom_generations"] = gens
        await pipeline_runner._save_state()
        return entry


async def _append_entry(entry: dict[str, Any]) -> None:
    async with pipeline_runner._STATE_LOCK:
        state = await pipeline_runner._load_state()
        gens = list(state.get("custom_generations") or [])
        gens.append(entry)
        state["custom_generations"] = gens
        await pipeline_runner._save_state()


# ---------------------------------------------------------------------------
# Ref upload
# ---------------------------------------------------------------------------


def save_uploaded_ref(filename: str, data: bytes) -> dict[str, Any]:
    """Speichert ein hochgeladenes Ref-Bild in CUSTOM_REFS_DIR mit timestamped
    Filename. Returns {path, name, size}."""
    suffix = Path(filename).suffix or ".png"
    suffix = suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError(f"Unsupported image format: {suffix}")
    stamp = int(time.time() * 1000)
    safe_base = _safe_filename(Path(filename).stem) or "ref"
    out_name = f"{stamp}_{safe_base}{suffix}"
    out_path = CUSTOM_REFS_DIR / out_name
    out_path.write_bytes(data)
    return {
        "path": _rel(out_path),
        "name": filename,
        "size": len(data),
    }


def list_refs(limit: int = 200) -> list[dict[str, Any]]:
    if not CUSTOM_REFS_DIR.exists():
        return []
    files = sorted(
        CUSTOM_REFS_DIR.iterdir(),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for p in files[:limit]:
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "path": _rel(p),
            "name": p.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
        })
    return out


def delete_ref(rel_path: str) -> None:
    target = (PROJECT_ROOT / rel_path).resolve()
    refs_root = CUSTOM_REFS_DIR.resolve()
    if refs_root not in target.parents and target != refs_root:
        raise ValueError("Refusing to delete outside custom-gen refs directory.")
    if target.exists():
        target.unlink()


# ---------------------------------------------------------------------------
# Generation - image
# ---------------------------------------------------------------------------


async def _run_image(gen_id: str) -> None:
    entry = next((g for g in await _load_list() if g.get("id") == gen_id), None)
    if not entry:
        return
    try:
        await _update_entry(gen_id, status="running", error=None)
        prompt = entry.get("prompt") or ""
        refs = [PROJECT_ROOT / p for p in (entry.get("refs") or [])]
        out_path = PROJECT_ROOT / entry["output_path"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        await aiauto_client.generate_image(
            prompt, out_path,
            reference_images=refs or None,
            aspect_ratio=entry.get("aspect_ratio") or "9:16",
            resolution=entry.get("resolution") or None,
            image_model=entry.get("model") or None,
        )
        await _update_entry(gen_id, status="done", output_path=_rel(out_path))
    except asyncio.CancelledError:
        await _update_entry(gen_id, status="cancelled", error="Manuell abgebrochen.")
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("custom-gen image failed gen_id=%s", gen_id)
        await _update_entry(gen_id, status="error", error=f"{type(exc).__name__}: {exc}")


async def enqueue_image(
    prompt: str,
    refs: list[str],
    model: str | None,
    aspect_ratio: str | None,
    resolution: str | None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt darf nicht leer sein.")
    gen_id = uuid.uuid4().hex[:12]
    stamp = int(time.time() * 1000)
    out_path = CUSTOM_GEN_DIR / f"img_{stamp}_{gen_id}.png"
    entry: dict[str, Any] = {
        "id": gen_id,
        "type": "image",
        "prompt": prompt.strip(),
        "refs": list(refs or []),
        "model": model or settings.aiauto_image_model,
        "aspect_ratio": aspect_ratio or "9:16",
        "resolution": resolution or settings.aiauto_image_resolution,
        "status": "queued",
        "output_path": _rel(out_path),
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await _append_entry(entry)
    task_key = f"custom-gen:{gen_id}"
    pipeline_runner._register_task(
        task_key, asyncio.create_task(_run_image(gen_id))
    )
    return gen_id


# ---------------------------------------------------------------------------
# Generation - video
# ---------------------------------------------------------------------------


async def _run_video(gen_id: str) -> None:
    entry = next((g for g in await _load_list() if g.get("id") == gen_id), None)
    if not entry:
        return
    try:
        await _update_entry(gen_id, status="running", error=None)
        prompt = entry.get("prompt") or ""
        refs = [PROJECT_ROOT / p for p in (entry.get("refs") or [])]
        out_path = PROJECT_ROOT / entry["output_path"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        await aiauto_client.generate_video(
            prompt, out_path,
            reference_images=refs or None,
            aspect_ratio=entry.get("aspect_ratio") or "9:16",
            resolution=entry.get("resolution") or None,
            seconds=entry.get("seconds"),
            model=entry.get("model") or None,
        )
        await _update_entry(gen_id, status="done", output_path=_rel(out_path))
    except asyncio.CancelledError:
        await _update_entry(gen_id, status="cancelled", error="Manuell abgebrochen.")
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("custom-gen video failed gen_id=%s", gen_id)
        await _update_entry(gen_id, status="error", error=f"{type(exc).__name__}: {exc}")


async def enqueue_video(
    prompt: str,
    refs: list[str],
    model: str | None,
    aspect_ratio: str | None,
    resolution: str | None,
    seconds: int | None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt darf nicht leer sein.")
    gen_id = uuid.uuid4().hex[:12]
    stamp = int(time.time() * 1000)
    out_path = CUSTOM_GEN_DIR / f"vid_{stamp}_{gen_id}.mp4"
    entry: dict[str, Any] = {
        "id": gen_id,
        "type": "video",
        "prompt": prompt.strip(),
        "refs": list(refs or []),
        "model": model or settings.aiauto_video_model,
        "aspect_ratio": aspect_ratio or "9:16",
        "resolution": resolution or settings.aiauto_video_quality,
        "seconds": int(seconds) if seconds else 5,
        "status": "queued",
        "output_path": _rel(out_path),
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await _append_entry(entry)
    task_key = f"custom-gen:{gen_id}"
    pipeline_runner._register_task(
        task_key, asyncio.create_task(_run_video(gen_id))
    )
    return gen_id


# ---------------------------------------------------------------------------
# Listing / cancel / delete
# ---------------------------------------------------------------------------


async def list_generations(limit: int = 100) -> list[dict[str, Any]]:
    gens = await _load_list()
    gens.sort(key=lambda g: g.get("created_at") or "", reverse=True)
    return gens[:limit]


async def cancel_generation(gen_id: str) -> None:
    task = pipeline_runner._TASKS.get(f"custom-gen:{gen_id}")
    if task and not task.done():
        task.cancel()
    else:
        await _update_entry(gen_id, status="cancelled", error="Bereits beendet.")


async def delete_generation(gen_id: str) -> None:
    async with pipeline_runner._STATE_LOCK:
        state = await pipeline_runner._load_state()
        gens = list(state.get("custom_generations") or [])
        idx = next((i for i, g in enumerate(gens) if g.get("id") == gen_id), -1)
        if idx < 0:
            return
        entry = gens[idx]
        out_rel = entry.get("output_path")
        gens.pop(idx)
        state["custom_generations"] = gens
        await pipeline_runner._save_state()
    if out_rel:
        out_abs = (PROJECT_ROOT / out_rel)
        try:
            if out_abs.exists():
                out_abs.unlink()
        except OSError:
            pass
