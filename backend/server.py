"""
FastAPI-Server. Bedient das Dashboard und die Pipeline-API.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import audio_editor, config, upscaler
from backend.clients import openai_client
from backend.pipeline import runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("fusion-auto")

app = FastAPI(title="Fusion Auto", version="0.1.0")


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class IdeasRequest(BaseModel):
    hint: str = Field(..., min_length=1, max_length=200)


class FusionIdea(BaseModel):
    pokemon_a: str
    pokemon_b: str
    concept: str = ""
    tone_hint: str | None = None


class BatchRequest(BaseModel):
    ideas: list[FusionIdea]


class FavoriteUpdate(BaseModel):
    variant: int | None = None


class ChecklistUpdate(BaseModel):
    key: str
    value: bool


class CustomPromptRequest(BaseModel):
    prompt: str


class RegenerateAllRequest(BaseModel):
    mode: str | None = None  # 'blend' / 'unique' / null (= globaler Setting)


class GenerateVideoRequest(BaseModel):
    tries: int = 1  # 1-3 parallele Video-Generations
    prompt_override: str | None = None  # optional: User-Custom-Prompt statt meta


class GenerateShowcaseRequest(BaseModel):
    prompt_override: str | None = None  # optional: Custom showcase-image-prompt


class GenerateFunnySceneRequest(BaseModel):
    gag_hint: str | None = None  # optional: User-Hint fuer den Gag (z.B. 'fire fart')


class SettingsUpdate(BaseModel):
    AIAUTO_API_KEY: str | None = None
    AIAUTO_BASE_URL: str | None = None
    AIAUTO_IMAGE_MODEL: str | None = None
    AIAUTO_IMAGE_RESOLUTION: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str | None = None
    GOOGLE_API_KEY: str | None = None
    GEMINI_VISION_MODEL: str | None = None
    VISION_PROVIDER: str | None = None
    STEP4_DESIGN_MODE: str | None = None
    NARRATION_WORDS_PER_FUSION: str | None = None


class RerunJobRequest(BaseModel):
    pokemon_a: str | None = None
    pokemon_b: str | None = None


class RegenerateNarrationRequest(BaseModel):
    words_per_fusion: int | None = None


# ---------------------------------------------------------------------------
# Startup-Check
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup() -> None:
    if not config.SIGNATURE_BACKGROUND_PATH.exists():
        log.warning(
            "Signature Background fehlt: %s - erste Pipeline-Runs werden fehlschlagen. "
            "Bitte PNG manuell platzieren.",
            config.SIGNATURE_BACKGROUND_PATH,
        )
    if not config.settings.aiauto_api_key:
        log.warning("AIAUTO_API_KEY ist nicht gesetzt. Im Dashboard unter Settings eintragen.")
    if not config.settings.openai_api_key:
        log.warning("OPENAI_API_KEY ist nicht gesetzt. Im Dashboard unter Settings eintragen.")


# ---------------------------------------------------------------------------
# API - Settings
# ---------------------------------------------------------------------------


@app.get("/api/settings")
async def api_get_settings() -> dict[str, Any]:
    return {
        "settings": config.settings.snapshot_public(),
        "signature_background_present": config.SIGNATURE_BACKGROUND_PATH.exists(),
    }


@app.post("/api/settings")
async def api_update_settings(req: SettingsUpdate) -> dict[str, Any]:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    changed = config.settings.update(updates)
    return {
        "changed": changed,
        "settings": config.settings.snapshot_public(),
    }


# ---------------------------------------------------------------------------
# API - Ideas
# ---------------------------------------------------------------------------


@app.post("/api/ideas")
async def api_generate_ideas(req: IdeasRequest) -> dict[str, Any]:
    try:
        ideas = await openai_client.generate_fusion_ideas(req.hint)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"hint": req.hint, "ideas": ideas}


# ---------------------------------------------------------------------------
# API - Fusion submit
# ---------------------------------------------------------------------------


@app.post("/api/fusion")
async def api_submit_fusion(idea: FusionIdea) -> dict[str, str]:
    job_id = await runner.submit_fusion(
        pokemon_a=idea.pokemon_a,
        pokemon_b=idea.pokemon_b,
        concept=idea.concept,
        tone_hint=idea.tone_hint,
    )
    return {"job_id": job_id}


@app.post("/api/fusion/batch")
async def api_submit_batch(req: BatchRequest) -> dict[str, Any]:
    if not req.ideas:
        raise HTTPException(status_code=400, detail="Keine Ideen im Batch.")
    ideas = [
        {
            "pokemon_a": i.pokemon_a,
            "pokemon_b": i.pokemon_b,
            "concept": i.concept,
            "tone_hint": i.tone_hint,
        }
        for i in req.ideas
    ]
    batch_id, job_ids = await runner.submit_batch(ideas)
    return {"batch_id": batch_id, "job_ids": job_ids}


@app.get("/api/batches")
async def api_list_batches() -> dict[str, Any]:
    return {"batches": await runner.list_batches()}


@app.get("/api/batches/{batch_id}")
async def api_get_batch(batch_id: str) -> dict[str, Any]:
    b = await runner.get_batch(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Batch nicht gefunden")
    return b


@app.post("/api/batches/{batch_id}/rerun")
async def api_rerun_batch(batch_id: str) -> dict[str, Any]:
    try:
        bid, new_ids = await runner.rerun_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"batch_id": bid, "new_job_ids": new_ids}


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str) -> dict[str, Any]:
    try:
        cancelled = await runner.cancel_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cancelled": cancelled}


@app.post("/api/jobs/{job_id}/rerun")
async def api_rerun_job(
    job_id: str, req: RerunJobRequest | None = None,
) -> dict[str, Any]:
    pa = (req.pokemon_a if req else None) or None
    pb = (req.pokemon_b if req else None) or None
    try:
        new_jid = await runner.rerun_job(job_id, pokemon_a=pa, pokemon_b=pb)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"new_job_id": new_jid}


@app.post("/api/jobs/{job_id}/regenerate-narration")
async def api_regenerate_narration(
    job_id: str, req: RegenerateNarrationRequest | None = None,
) -> dict[str, Any]:
    wpf = req.words_per_fusion if req else None
    if wpf is not None and not (5 <= wpf <= 60):
        raise HTTPException(status_code=400, detail="words_per_fusion muss zwischen 5 und 60 liegen.")
    try:
        result = await runner.regenerate_narration(job_id, words_per_fusion=wpf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return result


@app.post("/api/batches/{batch_id}/regenerate-narration")
async def api_regenerate_batch_narration(
    batch_id: str, req: RegenerateNarrationRequest | None = None,
) -> dict[str, Any]:
    wpf = req.words_per_fusion if req else None
    if wpf is not None and not (5 <= wpf <= 60):
        raise HTTPException(status_code=400, detail="words_per_fusion muss zwischen 5 und 60 liegen.")
    try:
        result = await runner.regenerate_batch_narration(batch_id, words_per_fusion=wpf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return result


@app.post("/api/batches/{batch_id}/cancel")
async def api_cancel_batch(batch_id: str) -> dict[str, Any]:
    try:
        count = await runner.cancel_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cancelled_count": count}


# ---------------------------------------------------------------------------
# API - Jobs
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
async def api_list_jobs() -> dict[str, Any]:
    return {"jobs": await runner.list_jobs()}


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str) -> dict[str, Any]:
    job = await runner.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return job


@app.post("/api/jobs/{job_id}/regenerate/{variant_index}")
async def api_regenerate(job_id: str, variant_index: int) -> dict[str, str]:
    try:
        await runner.regenerate_variant(job_id, variant_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued"}


@app.post("/api/jobs/{job_id}/regenerate-all")
async def api_regenerate_all(
    job_id: str, req: RegenerateAllRequest | None = None,
) -> dict[str, str]:
    mode = (req.mode if req else None) or None
    if isinstance(mode, str):
        mode = mode.strip().lower() or None
    try:
        await runner.regenerate_all_variants(job_id, design_mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued"}


@app.post("/api/jobs/{job_id}/regenerate-custom")
async def api_regenerate_custom(job_id: str, req: CustomPromptRequest) -> dict[str, str]:
    try:
        await runner.regenerate_all_variants_custom(job_id, req.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued"}


@app.post("/api/jobs/{job_id}/favorite")
async def api_set_favorite(job_id: str, req: FavoriteUpdate) -> dict[str, bool]:
    try:
        await runner.set_favorite(job_id, req.variant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/jobs/{job_id}/checklist")
async def api_toggle_checklist(job_id: str, req: ChecklistUpdate) -> dict[str, bool]:
    try:
        await runner.toggle_checklist(job_id, req.key, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/jobs/{job_id}/generate-showcase")
async def api_generate_showcase(
    job_id: str, req: GenerateShowcaseRequest | None = None,
) -> dict[str, str]:
    override = req.prompt_override if req else None
    try:
        await runner.generate_showcase_images(job_id, prompt_override=override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued"}


@app.post("/api/jobs/{job_id}/showcase-pick")
async def api_showcase_pick(job_id: str, req: FavoriteUpdate) -> dict[str, bool]:
    try:
        await runner.set_showcase_pick(job_id, req.variant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/jobs/{job_id}/generate-action-scene")
async def api_generate_action_scene(job_id: str) -> dict[str, str]:
    try:
        prompt = await runner.generate_action_scene(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": prompt}


@app.post("/api/jobs/{job_id}/regenerate-step5-prompt")
async def api_regenerate_step5_prompt(job_id: str) -> dict[str, str]:
    try:
        prompt = await runner.regenerate_step5_prompt(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": prompt}


@app.post("/api/jobs/{job_id}/regenerate-step6-prompt")
async def api_regenerate_step6_prompt(job_id: str) -> dict[str, str]:
    try:
        prompt = await runner.regenerate_step6_prompt(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": prompt}


@app.post("/api/jobs/{job_id}/check-eligibility/{variant}")
async def api_check_variant_eligibility(job_id: str, variant: int) -> dict[str, Any]:
    try:
        return await runner.check_variant_eligibility(job_id, variant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/eligibility-check")
async def api_check_uploaded_eligibility(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    image_bytes = await file.read()
    try:
        return await runner.check_uploaded_image_eligibility(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/manual-prompts")
async def api_manual_prompts(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Generiert Step 5 / Step 6 / Showcase-Image / Action-Scene Prompts
    fuer ein hochgeladenes Creature-Bild ausserhalb der Pipeline."""
    image_bytes = await file.read()
    try:
        return await runner.generate_manual_video_prompts(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/regenerate-showcase-image-prompt")
async def api_regenerate_showcase_image_prompt(job_id: str) -> dict[str, str]:
    try:
        prompt = await runner.regenerate_showcase_image_prompt(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": prompt}


@app.post("/api/jobs/{job_id}/regenerate-start-frame")
async def api_regenerate_start_frame(job_id: str) -> dict[str, str]:
    """Regeneriert das Step-3 Start-Frame (Side-by-Side beider Pokemon)."""
    try:
        path = await runner.regenerate_start_frame(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": path}


@app.post("/api/jobs/{job_id}/generate-step6-video")
async def api_generate_step6_video(
    job_id: str, req: GenerateVideoRequest | None = None,
) -> dict[str, Any]:
    tries = (req.tries if req else 1) or 1
    override = req.prompt_override if req else None
    try:
        await runner.generate_step6_video(job_id, tries=tries, prompt_override=override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "tries": min(3, max(1, tries))}


@app.post("/api/jobs/{job_id}/generate-action-scene-video")
async def api_generate_action_scene_video(
    job_id: str, req: GenerateVideoRequest | None = None,
) -> dict[str, Any]:
    tries = (req.tries if req else 1) or 1
    override = req.prompt_override if req else None
    try:
        await runner.generate_action_scene_video(job_id, tries=tries, prompt_override=override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "tries": min(3, max(1, tries))}


@app.post("/api/jobs/{job_id}/generate-funny-scene")
async def api_generate_funny_scene(
    job_id: str, req: GenerateFunnySceneRequest | None = None,
) -> dict[str, str]:
    gag_hint = (req.gag_hint if req else "") or ""
    try:
        prompt = await runner.generate_funny_scene(job_id, gag_hint=gag_hint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": prompt}


@app.post("/api/jobs/{job_id}/generate-funny-scene-video")
async def api_generate_funny_scene_video(
    job_id: str, req: GenerateVideoRequest | None = None,
) -> dict[str, Any]:
    tries = (req.tries if req else 1) or 1
    override = req.prompt_override if req else None
    try:
        await runner.generate_funny_scene_video(job_id, tries=tries, prompt_override=override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "tries": min(3, max(1, tries))}


@app.post("/api/jobs/{job_id}/generate-fusion-sequence-video")
async def api_generate_fusion_sequence_video(
    job_id: str, req: GenerateVideoRequest | None = None,
) -> dict[str, Any]:
    """Step 5 Fusion-Sequence Video (Seedance 2, 4k/5s).

    Beide Bilder als Reference: 03_start_frame.png + 04_fusion_v{fav}.png.
    Default-Prompt: meta.step5_transformation. Custom-Prompt via prompt_override.
    Kling First-Last-Frame manueller Fallback bleibt unangetastet.
    """
    tries = (req.tries if req else 1) or 1
    override = req.prompt_override if req else None
    try:
        await runner.generate_fusion_sequence_video(job_id, tries=tries, prompt_override=override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "tries": min(3, max(1, tries))}


@app.post("/api/jobs/{job_id}/generate-fusion-sequence-video-kling")
async def api_generate_fusion_sequence_video_kling(
    job_id: str, req: GenerateVideoRequest | None = None,
) -> dict[str, Any]:
    """Step 5 Fusion-Sequence Video via Kling 2.5 Turbo Pro (AI-Auto).

    Gleiche Refs/Prompts wie der Seedance-Pfad, aber mit Kling-Modell
    und Kling-typischer Quality/Duration (Default 1080p/5s, ueber
    AIAUTO_KLING_* Settings konfigurierbar). Output landet in
    fusion_sequence_videos[] mit Filename 05_fusion_sequence_kling_v*.mp4.
    """
    tries = (req.tries if req else 1) or 1
    override = req.prompt_override if req else None
    try:
        await runner.generate_fusion_sequence_video_kling(
            job_id, tries=tries, prompt_override=override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "tries": min(3, max(1, tries))}


# ---------------------------------------------------------------------------
# Upscaler (Real-ESRGAN ncnn-vulkan)
# ---------------------------------------------------------------------------


class UpscalerEnqueueRequest(BaseModel):
    input_path: str
    model: str = upscaler.DEFAULT_MODEL
    target_height: int = 2160  # 1440 | 2160 | 2880


@app.get("/api/upscaler/models")
async def api_upscaler_models() -> dict[str, Any]:
    return {
        "models": upscaler.list_models(),
        "default": upscaler.DEFAULT_MODEL,
        "target_heights": list(upscaler.VALID_TARGET_HEIGHTS),
    }


@app.get("/api/upscaler/status")
async def api_upscaler_status() -> dict[str, Any]:
    return await upscaler.get_status()


@app.post("/api/upscaler/enqueue")
async def api_upscaler_enqueue(req: UpscalerEnqueueRequest) -> dict[str, Any]:
    try:
        return await upscaler.enqueue_upscale(
            req.input_path, model=req.model, target_height=req.target_height,
        )
    except upscaler.UpscalerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/upscaler/cancel/{job_id}")
async def api_upscaler_cancel(job_id: str) -> dict[str, Any]:
    try:
        return await upscaler.cancel_job(job_id)
    except upscaler.UpscalerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/upscaler/job/{job_id}")
async def api_upscaler_remove(job_id: str) -> dict[str, Any]:
    try:
        removed = await upscaler.remove_job(job_id)
    except upscaler.UpscalerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"removed": removed}


@app.post("/api/upscaler/clear")
async def api_upscaler_clear() -> dict[str, Any]:
    count = await upscaler.clear_finished()
    return {"cleared": count}


@app.post("/api/upscaler/upload")
async def api_upscaler_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Saves an uploaded video into output/_upscaler_uploads/ and returns
    the project-relative path. Streamed in 1 MB chunks to avoid OOM."""
    import os as _os
    import uuid as _uuid

    raw_name = (file.filename or "upload.mp4")
    suffix = ""
    lower = raw_name.lower()
    for ext in upscaler.UPLOAD_ALLOWED_EXTS:
        if lower.endswith(ext):
            suffix = ext
            break
    if not suffix:
        raise HTTPException(
            status_code=400,
            detail=(
                "Nur Video-Container erlaubt: "
                + ", ".join(sorted(upscaler.UPLOAD_ALLOWED_EXTS))
            ),
        )

    # Sanitize base name: keep alnum/-/_/dot, replace rest with underscore.
    stem = Path(raw_name).stem
    safe_stem = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in stem)[:80]
    if not safe_stem:
        safe_stem = "upload"
    target_name = f"{safe_stem}_{_uuid.uuid4().hex[:8]}{suffix}"
    target_path = upscaler.UPSCALER_UPLOADS_DIR / target_name

    written = 0
    upscaler.UPSCALER_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with target_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB
                if not chunk:
                    break
                written += len(chunk)
                if written > upscaler.UPLOAD_MAX_BYTES:
                    f.close()
                    try:
                        target_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload zu gross (max {upscaler.UPLOAD_MAX_BYTES // (1024*1024)} MB).",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            target_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    if written == 0:
        try:
            target_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Leeres File.")

    rel_path = str(target_path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    return {
        "path": rel_path,
        "absolute_path": str(target_path),
        "size_bytes": written,
        "original_name": raw_name,
    }


# ---------------------------------------------------------------------------
# Audio Editor (Narration Pause Analyzer & Remover)
# ---------------------------------------------------------------------------


@app.post("/api/audio-editor/analyze")
async def api_audio_editor_analyze(
    file: UploadFile = File(...),
    silence_thresh_db: float = -35.0,
    min_silence_ms: int = 300,
    offset_before: float = 0.1,
    offset_after: float = 0.05,
) -> dict[str, Any]:
    """Single-shot Endpoint: Detection + Stats + Waveforms + Silence-Removal.

    Limit: 50 MB Upload. Erlaubte Container: mp3 / wav / m4a (ffmpeg liest
    eh fast alles, der Filter ist nur Schutz vor versehentlichem Bild-Upload).
    """
    import os
    import tempfile
    import uuid

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Leeres Audio-File.")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio zu gross (max 50 MB).")

    # Suffix aus Content-Type / Filename ableiten - ffmpeg ist tolerant.
    fname = (file.filename or "input.mp3").lower()
    suffix = ".mp3"
    for ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
        if fname.endswith(ext):
            suffix = ext
            break

    src_fd, src_path_str = tempfile.mkstemp(prefix="audio_src_", suffix=suffix)
    os.close(src_fd)
    src_path = config.AUDIO_EDITOR_DIR / f"src_{uuid.uuid4().hex}{suffix}"
    edited_path = config.AUDIO_EDITOR_DIR / f"edited_{uuid.uuid4().hex}.mp3"
    try:
        # Source-Datei in den persistent dir schreiben (loeschen wir am Ende
        # des Requests). Streamlit-Aequivalent zu st.session_state.
        src_path.write_bytes(raw)

        original = await audio_editor.get_audio_samples(src_path, max_points=2000)
        silences = await audio_editor.detect_silences(
            src_path,
            silence_thresh_db=silence_thresh_db,
            min_silence_ms=min_silence_ms,
        )
        await audio_editor.remove_silences(
            src_path, edited_path, silences,
            offset_before=offset_before, offset_after=offset_after,
        )
        edited = await audio_editor.get_audio_samples(edited_path, max_points=2000)
        stats = audio_editor.get_silence_stats(silences, original.get("duration", 0.0))
    except audio_editor.FFmpegMissingError as exc:
        # Source aufraeumen
        try:
            src_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        try:
            src_path.unlink(missing_ok=True)
            edited_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    else:
        # Source koennen wir nach erfolgreichem Edit weg - nur das Ergebnis
        # bleibt liegen fuer Download / Player.
        try:
            src_path.unlink(missing_ok=True)
        except Exception:
            pass
    finally:
        # Tempfile vom mkstemp-Call (haben wir nicht genutzt) auch loeschen
        try:
            os.unlink(src_path_str)
        except OSError:
            pass

    edited_url = "/output/_audio_editor/" + edited_path.name
    return {
        "original": original,
        "edited": {**edited, "url": edited_url, "filename": edited_path.name},
        "silences": silences,
        "stats": stats,
        "params": {
            "silence_thresh_db": silence_thresh_db,
            "min_silence_ms": min_silence_ms,
            "offset_before": offset_before,
            "offset_after": offset_after,
        },
    }


# ---------------------------------------------------------------------------
# Static mounts + Dashboard
# ---------------------------------------------------------------------------

# Output-Ordner statisch servieren, damit das Dashboard Thumbnails zeigen kann.
app.mount("/output", StaticFiles(directory=str(config.OUTPUT_DIR)), name="output")
# Assets (signature background) - nur informativ.
app.mount("/assets", StaticFiles(directory=str(config.ASSETS_DIR)), name="assets")


@app.get("/")
async def dashboard_index() -> FileResponse:
    index = config.DASHBOARD_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            {"error": "dashboard/index.html fehlt"}, status_code=500
        )
    return FileResponse(
        str(index),
        headers={
            # Dashboard hat keinen Build-Prozess - wir wollen garantiert
            # frische HTML/CSS/JS-Version nach jedem git pull.
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
