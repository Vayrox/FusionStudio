"""
FastAPI-Server. Bedient das Dashboard und die Pipeline-API.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config
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


class SettingsUpdate(BaseModel):
    AIAUTO_API_KEY: str | None = None
    AIAUTO_BASE_URL: str | None = None
    AIAUTO_IMAGE_MODEL: str | None = None
    AIAUTO_IMAGE_RESOLUTION: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str | None = None


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
async def api_rerun_job(job_id: str) -> dict[str, Any]:
    try:
        new_jid = await runner.rerun_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"new_job_id": new_jid}


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
async def api_regenerate_all(job_id: str) -> dict[str, str]:
    try:
        await runner.regenerate_all_variants(job_id)
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
async def api_generate_showcase(job_id: str) -> dict[str, str]:
    try:
        await runner.generate_showcase_images(job_id)
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
