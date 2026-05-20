"""
Real-ESRGAN-ncnn-vulkan video upscaler with a serial queue.

Pipeline pro Job:
  1. Frames als PNG via ffmpeg extrahieren
  2. Frames via realesrgan-ncnn-vulkan hochskalieren (4x, intern via Vulkan)
  3. Skalierte Frames + Original-Audio via ffmpeg zu mp4 zusammenbauen
     (mit lanczos-Downscale auf die gewuenschte Ziel-Aufloesung,
      libx264, crf 17, preset slower)

Queue-Logik:
  - Beliebig viele Jobs koennen enqueued werden.
  - Ein einzelner Worker-Task pickt sequentiell den naechsten 'queued' job
    und arbeitet ihn ab. GPU laeuft nicht zwei Jobs parallel - das waere
    halb so schnell + ggf. VRAM-OOM, hier serialisieren wir bewusst.
  - Cancel auf laufendem Job killt das subprocess + markiert cancelled.
  - Cancel auf wartendem Job markiert cancelled (Worker skipped es).

Einmaliger Setup: bei erstem Aufruf wird die offizielle ncnn-Vulkan-Binary
vom xinntao/Real-ESRGAN-Release nach `vendor/realesrgan/` heruntergeladen
und entpackt (~28 MB, danach lokal).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import OUTPUT_DIR, PROJECT_ROOT

log = logging.getLogger("fusion-auto.upscaler")


# ---------------------------------------------------------------------------
# Real-ESRGAN binary discovery + lazy install
# ---------------------------------------------------------------------------

REALESRGAN_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
)
VENDOR_DIR = PROJECT_ROOT / "vendor" / "realesrgan"
_BINARY_NAME = "realesrgan-ncnn-vulkan" + (".exe" if os.name == "nt" else "")


def _resolve_ffmpeg(name: str) -> str:
    exe_name = name + (".exe" if os.name == "nt" else "")
    env_dir = os.environ.get("FUSIONSTUDIO_FFMPEG_DIR")
    if env_dir:
        cand = Path(env_dir) / exe_name
        if cand.exists():
            return str(cand)
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        cand = Path(bundle_dir) / "vendor" / "ffmpeg" / exe_name
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    return found or name


_FFMPEG = _resolve_ffmpeg("ffmpeg")
_FFPROBE = _resolve_ffmpeg("ffprobe")


UPSCALER_OUTPUT_DIR = OUTPUT_DIR / "_upscaled"
UPSCALER_TEMP_DIR = OUTPUT_DIR / "_upscaler_tmp"
UPSCALER_UPLOADS_DIR = OUTPUT_DIR / "_upscaler_uploads"
UPSCALER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPSCALER_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


UPLOAD_MAX_BYTES = 500 * 1024 * 1024  # 500 MB
UPLOAD_ALLOWED_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


MODEL_INFO: dict[str, dict[str, Any]] = {
    "realesrgan-x4plus": {
        "label": "RealESRGAN x4plus (general / photorealistic)",
        "best_for": "Photorealistic Seedance / Kling Footage",
    },
    "realesrnet-x4plus": {
        "label": "RealESRNet x4plus (smoother, less hallucination)",
        "best_for": "Wenn x4plus zu kuenstlich scharf aussieht",
    },
    "realesrgan-x4plus-anime": {
        "label": "RealESRGAN x4plus anime (stylized, sharper)",
        "best_for": "Cartoon / Anime / cell-shaded Stil",
    },
    "realesr-animevideov3": {
        "label": "RealESR AnimeVideo v3 (video-optimized stylized)",
        "best_for": "Stylized Videos mit temporaler Konsistenz (Pokemon-Style)",
    },
}
DEFAULT_MODEL = "realesrgan-x4plus"
VALID_TARGET_HEIGHTS = (1440, 2160, 2880)

# Wenn die Queue ueber MAX_KEPT_FINISHED done/error/cancelled-Eintraege hat,
# werden die aeltesten beim Enqueue automatisch abgeschnitten. So waechst die
# Liste nicht unkontrolliert. Aktive Jobs (queued/running) sind davon nie
# betroffen.
MAX_KEPT_FINISHED = 50


class UpscalerError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Binary install
# ---------------------------------------------------------------------------


async def ensure_installed() -> Path:
    bin_path = VENDOR_DIR / _BINARY_NAME
    models_dir = VENDOR_DIR / "models"
    if bin_path.exists() and models_dir.exists():
        return bin_path

    if os.name != "nt":
        raise UpscalerError(
            "Auto-Install der Real-ESRGAN-Binary ist aktuell nur fuer Windows "
            "implementiert. Manuell von https://github.com/xinntao/Real-ESRGAN/releases "
            f"runterladen und nach {VENDOR_DIR} entpacken."
        )

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = VENDOR_DIR / "_download.zip"
    log.info("Downloading Real-ESRGAN binary from %s", REALESRGAN_URL)

    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        async with client.stream("GET", REALESRGAN_URL) as resp:
            resp.raise_for_status()
            with zip_path.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)

    log.info("Extracting Real-ESRGAN to %s", VENDOR_DIR)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(VENDOR_DIR)
    zip_path.unlink(missing_ok=True)

    if not bin_path.exists():
        for cand in VENDOR_DIR.rglob(_BINARY_NAME):
            if cand == bin_path:
                continue
            shutil.move(str(cand), str(bin_path))
            src_models = cand.parent / "models"
            if src_models.exists() and not models_dir.exists():
                shutil.move(str(src_models), str(models_dir))
            try:
                shutil.rmtree(cand.parent, ignore_errors=True)
            except OSError:
                pass
            break

    if not bin_path.exists():
        raise UpscalerError(f"Real-ESRGAN binary not found after install at {bin_path}")
    if not models_dir.exists():
        raise UpscalerError(f"Real-ESRGAN models folder not found at {models_dir}")

    log.info("Real-ESRGAN installed: %s", bin_path)
    return bin_path


# ---------------------------------------------------------------------------
# Queue state
# ---------------------------------------------------------------------------

_STATE_LOCK = asyncio.Lock()
_QUEUE: list[dict[str, Any]] = []
_WORKER_TASK: asyncio.Task[None] | None = None
_RUNNING_PROC: subprocess.Popen[Any] | None = None
_RUNNING_JOB_ID: str | None = None


def _find_job(job_id: str) -> dict[str, Any] | None:
    return next((j for j in _QUEUE if j["id"] == job_id), None)


def _set_progress(job_id: str, stage: str, pct: float, **extra: Any) -> None:
    """Thread-safe-ish progress update (GIL covers single-dict writes)."""
    job = _find_job(job_id)
    if job is None:
        return
    job["stage"] = stage
    job["progress"] = round(max(0.0, min(100.0, pct)), 1)
    job["updated_at"] = _now_iso()
    for k, v in extra.items():
        job[k] = v


def _prune_finished_locked() -> None:
    """Trim oldest done/error/cancelled when queue grows too large.
    Caller must hold _STATE_LOCK."""
    finished_indices = [
        i for i, j in enumerate(_QUEUE)
        if j["status"] in ("done", "error", "cancelled")
    ]
    excess = len(finished_indices) - MAX_KEPT_FINISHED
    if excess <= 0:
        return
    # Drop oldest first
    to_remove = set(finished_indices[:excess])
    _QUEUE[:] = [j for i, j in enumerate(_QUEUE) if i not in to_remove]


# ---------------------------------------------------------------------------
# Video probe / synchronous upscale worker
# ---------------------------------------------------------------------------


def _probe_video_sync(video: Path) -> dict[str, Any]:
    cmd = [
        _FFPROBE, "-v", "error",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise UpscalerError(f"ffprobe failed: {proc.stderr[:300]}")
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        raise UpscalerError(f"Kein Video-Stream in {video.name}")
    w = int(v["width"])
    h = int(v["height"])
    fps_raw = v.get("r_frame_rate", "30/1")
    if "/" in fps_raw:
        num, den = fps_raw.split("/", 1)
        try:
            fps = float(num) / float(den) if float(den) else 30.0
        except ZeroDivisionError:
            fps = 30.0
    else:
        fps = float(fps_raw)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return {"width": w, "height": h, "fps": fps, "duration": duration, "has_audio": has_audio}


def _do_upscale_sync(
    bin_path: Path,
    input_path: Path,
    output_path: Path,
    model: str,
    target_height: int,
    job_temp_dir: Path,
    meta: dict[str, Any],
    job_id: str,
) -> None:
    """Komplette Upscale-Pipeline. Laeuft in einem worker thread."""
    global _RUNNING_PROC

    frames_in = job_temp_dir / "frames_in"
    frames_out = job_temp_dir / "frames_out"
    frames_in.mkdir(parents=True, exist_ok=True)
    frames_out.mkdir(parents=True, exist_ok=True)

    # ---- Stage 1: extract frames ----
    _set_progress(job_id, "extract", 0.0)
    cmd_extract = [
        _FFMPEG, "-y",
        "-i", str(input_path),
        str(frames_in / "%08d.png"),
    ]
    log.info("[%s] ffmpeg extract: %s", job_id, " ".join(cmd_extract))
    _RUNNING_PROC = subprocess.Popen(
        cmd_extract,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _RUNNING_PROC.wait()
    rc_extract = _RUNNING_PROC.returncode
    _RUNNING_PROC = None
    if rc_extract != 0:
        raise UpscalerError(f"ffmpeg frame extraction failed (exit {rc_extract})")

    total_frames = sum(1 for _ in frames_in.glob("*.png"))
    if total_frames == 0:
        raise UpscalerError("Keine Frames extrahiert - ffmpeg konnte das Video nicht lesen")
    _set_progress(job_id, "extract", 100.0, total_frames=total_frames)

    # ---- Stage 2: Real-ESRGAN upscale ----
    _set_progress(job_id, "upscale", 0.0, frames_done=0)
    cmd_upscale = [
        str(bin_path),
        "-i", str(frames_in),
        "-o", str(frames_out),
        "-n", model,
        "-s", "4",
        "-m", str(VENDOR_DIR / "models"),
        "-f", "png",
    ]
    log.info("[%s] Real-ESRGAN upscale: %s", job_id, " ".join(cmd_upscale))
    _RUNNING_PROC = subprocess.Popen(
        cmd_upscale,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    while True:
        try:
            returncode = _RUNNING_PROC.wait(timeout=2.0)
            break
        except subprocess.TimeoutExpired:
            done = sum(1 for _ in frames_out.glob("*.png"))
            pct = (done / total_frames * 100.0) if total_frames else 0.0
            _set_progress(job_id, "upscale", pct, frames_done=done)
    _RUNNING_PROC = None
    if returncode != 0:
        raise UpscalerError(
            f"Real-ESRGAN exited {returncode}. Pruefe ob deine GPU Vulkan unterstuetzt "
            f"(https://vulkan.gpuinfo.org). Bei NVIDIA: aktuelle Treiber installieren."
        )
    _set_progress(job_id, "upscale", 100.0, frames_done=total_frames)

    # ---- Stage 3: reassemble video ----
    _set_progress(job_id, "assemble", 0.0)
    target_w = int(round(meta["width"] * target_height / meta["height"]))
    if target_w % 2:
        target_w += 1
    target_h = target_height + (target_height % 2)

    cmd_assemble: list[str] = [
        _FFMPEG, "-y",
        "-framerate", f"{meta['fps']:.6f}",
        "-i", str(frames_out / "%08d.png"),
        "-i", str(input_path),
        "-map", "0:v:0",
    ]
    if meta["has_audio"]:
        cmd_assemble += ["-map", "1:a:0", "-c:a", "copy"]
    else:
        cmd_assemble += ["-map", "-1:a"]
    cmd_assemble += [
        "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
        "-c:v", "libx264",
        "-preset", "slower",
        "-crf", "17",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_path),
    ]
    log.info("[%s] ffmpeg assemble: %s", job_id, " ".join(cmd_assemble))
    _RUNNING_PROC = subprocess.Popen(
        cmd_assemble,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    duration = meta.get("duration", 0.0) or 0.0
    time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
    if _RUNNING_PROC.stderr is not None:
        for line in _RUNNING_PROC.stderr:
            m = time_re.search(line)
            if m and duration > 0:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                _set_progress(job_id, "assemble", min(99.0, t / duration * 100.0))
    _RUNNING_PROC.wait()
    rc_assemble = _RUNNING_PROC.returncode
    _RUNNING_PROC = None
    if rc_assemble != 0:
        raise UpscalerError(f"ffmpeg assemble failed (exit {rc_assemble})")
    _set_progress(job_id, "assemble", 100.0)

    try:
        shutil.rmtree(frames_in, ignore_errors=True)
        shutil.rmtree(frames_out, ignore_errors=True)
        job_temp_dir.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


async def _process_job(job: dict[str, Any]) -> None:
    """Run one job. Sets state to running, executes the pipeline, raises on
    failure. The caller (_worker) handles final status transitions."""
    global _RUNNING_JOB_ID

    input_path = Path(job["input_path"])
    output_path = Path(job["output_path"])
    job_temp_dir = Path(job["temp_dir"])
    job_id = job["id"]

    _RUNNING_JOB_ID = job_id
    try:
        _set_progress(job_id, "install", 0.0)
        bin_path = await ensure_installed()
        _set_progress(job_id, "install", 100.0)

        _set_progress(job_id, "probe", 0.0)
        meta = await asyncio.to_thread(_probe_video_sync, input_path)
        _set_progress(job_id, "probe", 100.0, source_meta=meta)

        await asyncio.to_thread(
            _do_upscale_sync,
            bin_path, input_path, output_path,
            job["model"], job["target_height"],
            job_temp_dir, meta, job_id,
        )
    finally:
        _RUNNING_JOB_ID = None


async def _worker_loop() -> None:
    """Single worker that drains the queue serially. Exits when no queued
    jobs are left so we don't keep an idle task running."""
    global _WORKER_TASK
    try:
        while True:
            async with _STATE_LOCK:
                job = next((j for j in _QUEUE if j["status"] == "queued"), None)
                if job is None:
                    _WORKER_TASK = None
                    return
                job["status"] = "running"
                job["started_at"] = _now_iso()
                job["updated_at"] = _now_iso()
                current_job_id = job["id"]
            log.info("Upscale worker picked job %s (%s)", job["id"], job["input_name"])
            try:
                await _process_job(job)
                async with _STATE_LOCK:
                    cur = _find_job(current_job_id)
                    if cur is not None and cur["status"] == "running":
                        cur["status"] = "done"
                        cur["progress"] = 100.0
                        cur["stage"] = "done"
                        cur["completed_at"] = _now_iso()
                        cur["updated_at"] = _now_iso()
            except Exception as exc:  # noqa: BLE001
                log.exception("Upscale job %s failed", current_job_id)
                async with _STATE_LOCK:
                    cur = _find_job(current_job_id)
                    if cur is not None and cur["status"] != "cancelled":
                        cur["status"] = "error"
                        cur["error"] = f"{type(exc).__name__}: {exc}"
                        cur["completed_at"] = _now_iso()
                        cur["updated_at"] = _now_iso()
    except asyncio.CancelledError:
        log.info("Upscale worker cancelled")
        raise


def _ensure_worker_running() -> None:
    """Schedule the worker if it isn't running. Must be called from the
    same event loop as the FastAPI server."""
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(_worker_loop())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_input_path(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    return p


async def get_status() -> dict[str, Any]:
    async with _STATE_LOCK:
        return {
            "queue": [dict(j) for j in _QUEUE],
            "worker_active": _WORKER_TASK is not None and not _WORKER_TASK.done(),
            "running_id": _RUNNING_JOB_ID,
        }


async def enqueue_upscale(
    input_path_raw: str,
    model: str = DEFAULT_MODEL,
    target_height: int = 2160,
) -> dict[str, Any]:
    """Append a new job to the queue. Starts the worker if needed."""
    input_path = _resolve_input_path(input_path_raw)

    if model not in MODEL_INFO:
        raise UpscalerError(
            f"Unbekanntes Model: {model!r}. Erlaubt: {list(MODEL_INFO)}"
        )
    if target_height not in VALID_TARGET_HEIGHTS:
        raise UpscalerError(
            f"target_height muss 1440 / 2160 / 2880 sein, bekommen: {target_height}"
        )
    if not input_path.exists():
        raise UpscalerError(f"Eingabe-Video nicht gefunden: {input_path}")

    UPSCALER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPSCALER_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    job_id = _make_id()
    stem = input_path.stem
    out_name = f"{stem}_upscaled_{target_height}p.mp4"
    output_path = UPSCALER_OUTPUT_DIR / out_name
    # Kollision auf Disk ODER mit einem anderen Job in der Queue (Step 5
    # Videos teilen sich oft denselben Stem, z.B. 05_fusion_sequence_video_v1.mp4
    # ueber mehrere Fusionen) -> Job-ID anhaengen damit nichts ueberschrieben wird.
    async with _STATE_LOCK:
        queued_outputs = {Path(j["output_path"]) for j in _QUEUE
                          if j["status"] in ("queued", "running")}
    if output_path.exists() or output_path in queued_outputs:
        out_name = f"{stem}_upscaled_{target_height}p_{job_id}.mp4"
        output_path = UPSCALER_OUTPUT_DIR / out_name

    job: dict[str, Any] = {
        "id": job_id,
        "status": "queued",
        "input_path": str(input_path),
        "input_name": input_path.name,
        "output_path": str(output_path),
        "output_rel": str(output_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "temp_dir": str(UPSCALER_TEMP_DIR / f"job_{job_id}"),
        "model": model,
        "target_height": target_height,
        "stage": "queued",
        "progress": 0.0,
        "total_frames": 0,
        "frames_done": 0,
        "enqueued_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "updated_at": _now_iso(),
        "error": None,
        "source_meta": None,
    }

    async with _STATE_LOCK:
        _QUEUE.append(job)
        _prune_finished_locked()
    _ensure_worker_running()
    return dict(job)


async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued or running job. For queued jobs it's just a status
    flip. For the running job we kill the active subprocess + flip status -
    the worker's except branch then keeps the cancelled marker."""
    global _RUNNING_PROC
    async with _STATE_LOCK:
        job = _find_job(job_id)
        if job is None:
            raise UpscalerError(f"Job {job_id} nicht gefunden")
        if job["status"] in ("done", "error", "cancelled"):
            return dict(job)
        was_running = job["status"] == "running"
        job["status"] = "cancelled"
        job["completed_at"] = _now_iso()
        job["updated_at"] = _now_iso()

    if was_running:
        proc = _RUNNING_PROC
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("Cancel: subprocess kill failed: %s", exc)
        _RUNNING_PROC = None

    async with _STATE_LOCK:
        return dict(_find_job(job_id) or {})


async def remove_job(job_id: str) -> bool:
    """Remove a finished (done/error/cancelled) job entry. Aktive Jobs
    bleiben unangetastet - die muss man erst cancellen."""
    async with _STATE_LOCK:
        job = _find_job(job_id)
        if job is None:
            return False
        if job["status"] not in ("done", "error", "cancelled"):
            raise UpscalerError(
                "Aktive Jobs kannst du nicht entfernen - erst cancellen."
            )
        _QUEUE[:] = [j for j in _QUEUE if j["id"] != job_id]
        return True


async def clear_finished() -> int:
    """Remove all done/error/cancelled jobs. Returns count removed."""
    async with _STATE_LOCK:
        before = len(_QUEUE)
        _QUEUE[:] = [j for j in _QUEUE if j["status"] not in ("done", "error", "cancelled")]
        return before - len(_QUEUE)


def list_models() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in MODEL_INFO.items()]
