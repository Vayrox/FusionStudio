"""
Pipeline-Orchestrator. Fuehrt fuer jede Fusion die Steps 2A, 2B, 3, Traits,
4 (x5 Varianten), 5, 6, Narration aus und schreibt Output-Assets.

State-Persistenz: .state/jobs.json ueberlebt Browser-Refresh und Server-Neustart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from backend import prompts

log = logging.getLogger("fusion-auto.pipeline")
from backend.clients import aiauto_client, openai_client, pokemon_refs
from backend.config import (
    MAX_PARALLEL_FUSIONS,
    OUTPUT_DIR,
    PROJECT_ROOT,
    REALISTIC_CACHE_DIR,
    SHOWCASE_VARIANTS,
    SIGNATURE_BACKGROUND_PATH,
    STATE_FILE,
    STEP4_VARIANTS,
    settings,
)

# ---------------------------------------------------------------------------
# Job-Semaphore + State
# ---------------------------------------------------------------------------

_FUSION_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_FUSIONS)
_STATE_LOCK = asyncio.Lock()
_STATE_CACHE: dict[str, Any] | None = None

# Laufende asyncio-Tasks pro job_id, damit Stop-Endpoints sie abbrechen koennen.
# Der Key ist die job_id (oder "batch:<id>" fuer Batch-Monitore).
_TASKS: dict[str, asyncio.Task[Any]] = {}


def _register_task(key: str, task: asyncio.Task[Any]) -> None:
    _TASKS[key] = task
    task.add_done_callback(lambda _t, k=key: _TASKS.pop(k, None))


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# 16:9 Split-Ref Canvas-Groesse - 1920x1080 ist gross genug fuer Seedance's
# 4K Output ohne dass die Halbe-Pokemon-Refs zu klein wirken (jede Haelfte
# 960x1080).
_MORPH_SPLIT_CANVAS_W = 1920
_MORPH_SPLIT_CANVAS_H = 1080


def _build_fusion_morph_split_ref(
    start_frame: Path, end_frame: Path, out_path: Path,
) -> Path:
    """Baut ein 16:9 Side-by-Side Ref-Bild fuer Seedance/Kling Morph-Videos.

    Seedance/Kling akzeptieren nur EIN reference_asset. Statt nur den Start-
    Frame zu schicken (Modell sieht End-Zustand nicht), legen wir Start und
    End in einer Kachel zusammen: LEFT=start, RIGHT=end, beide center-fitted
    auf schwarzem Background, Aspect Ratios bleiben erhalten (Letterboxing).
    Der Prompt-Prefix erklaert dem Modell wie die Kachel zu lesen ist.
    """
    canvas_w = _MORPH_SPLIT_CANVAS_W
    canvas_h = _MORPH_SPLIT_CANVAS_H
    half_w = canvas_w // 2
    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))

    for path, x_origin in ((start_frame, 0), (end_frame, half_w)):
        with Image.open(path) as src:
            src.load()
            img = src.convert("RGB")
        scale = min(half_w / img.width, canvas_h / img.height)
        new_w = max(1, int(round(img.width * scale)))
        new_h = max(1, int(round(img.height * scale)))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        paste_x = x_origin + (half_w - new_w) // 2
        paste_y = (canvas_h - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))

    canvas.save(out_path, format="PNG", optimize=True)
    return out_path


_MORPH_SPLIT_PROMPT_LEGEND = (
    "REFERENCE IMAGE LAYOUT: The input reference image is a 16:9 canvas "
    "split exactly in half. The LEFT half shows the STARTING STATE (two "
    "separate Pokemon standing side by side). The RIGHT half shows the END "
    "STATE (the single fused creature). Animate a smooth morph / "
    "transformation from the LEFT-side composition INTO the RIGHT-side "
    "composition. CRITICAL: do NOT keep the side-by-side split layout in "
    "the output video. The output is a single continuous scene that starts "
    "looking like the LEFT half and ends looking like the RIGHT half - "
    "never show both halves at the same time, never show a vertical seam.\n\n"
)


def _load_state_sync() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"jobs": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"jobs": {}}


async def _load_state() -> dict[str, Any]:
    global _STATE_CACHE
    if _STATE_CACHE is None:
        _STATE_CACHE = _load_state_sync()
    return _STATE_CACHE


async def _save_state() -> None:
    assert _STATE_CACHE is not None
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_STATE_CACHE, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


async def _update_job(job_id: str, **patch: Any) -> dict[str, Any]:
    async with _STATE_LOCK:
        state = await _load_state()
        job = state["jobs"].setdefault(job_id, {"id": job_id})
        job.update(patch)
        job["updated_at"] = _now_iso()
        await _save_state()
        snapshot = dict(job)
    # Live-Log pro Step-Transition damit man im Terminal sieht wo jeder Job steht
    if "current_step" in patch:
        log.warning(
            "job %s [%s x %s] -> %s (status=%s)",
            job_id,
            snapshot.get("pokemon_a"),
            snapshot.get("pokemon_b"),
            patch.get("current_step"),
            snapshot.get("status"),
        )
    return snapshot


async def get_job(job_id: str) -> dict[str, Any] | None:
    state = await _load_state()
    job = state["jobs"].get(job_id)
    return dict(job) if job else None


async def list_jobs() -> list[dict[str, Any]]:
    state = await _load_state()
    jobs = list(state["jobs"].values())
    # Neueste zuerst
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return [dict(j) for j in jobs]


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


async def _update_batch(batch_id: str, **patch: Any) -> dict[str, Any]:
    async with _STATE_LOCK:
        state = await _load_state()
        batches = state.setdefault("batches", {})
        batch = batches.setdefault(batch_id, {"id": batch_id})
        batch.update(patch)
        batch["updated_at"] = _now_iso()
        await _save_state()
        return dict(batch)


async def get_batch(batch_id: str) -> dict[str, Any] | None:
    state = await _load_state()
    batch = state.get("batches", {}).get(batch_id)
    return dict(batch) if batch else None


async def list_batches() -> list[dict[str, Any]]:
    state = await _load_state()
    batches = list(state.get("batches", {}).values())
    batches.sort(key=lambda b: b.get("created_at", ""), reverse=True)
    return [dict(b) for b in batches]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _folder_slug(name: str) -> str:
    s = _SLUG_RE.sub("_", name.lower()).strip("_")
    return s or "unknown"


def _make_output_dir(pokemon_a: str, pokemon_b: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{_folder_slug(pokemon_a)}_{_folder_slug(pokemon_b)}_{ts}"
    path = OUTPUT_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _realistic_cache_path(pokemon_name: str) -> Path:
    slug = pokemon_refs.pokemon_slug(pokemon_name)
    return REALISTIC_CACHE_DIR / f"{slug}.png"


async def _step2_realistic_cached(
    pokemon_name: str, ref_image: Path, output_path: Path
) -> tuple[Path, bool]:
    """Step 2 mit Cache - gibt (output_path, used_cache) zurueck.

    Cache-Key ist der PokeAPI-Slug. Bei Hit wird die gecachte Datei in
    den Output-Ordner kopiert (so bleibt die Pipeline-Output-Struktur
    konsistent). Bei Miss wird AI-Auto angefragt und das Ergebnis in
    den Cache geschrieben (atomar via .tmp+rename).
    """
    cache_path = _realistic_cache_path(pokemon_name)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache_path, output_path)
        return output_path, True

    prompt = prompts.STEP2_REALISTIC_SINGLE.replace("{POKEMON}", pokemon_name)
    await aiauto_client.generate_image(
        prompt, output_path, reference_images=[ref_image]
    )
    if output_path.exists() and output_path.stat().st_size > 0:
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        try:
            shutil.copyfile(output_path, tmp)
            tmp.replace(cache_path)
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    return output_path, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def submit_fusion(
    pokemon_a: str,
    pokemon_b: str,
    concept: str = "",
    tone_hint: str | None = None,
    batch_id: str | None = None,
) -> str:
    """Queued eine neue Fusion. Gibt job_id zurueck. Pipeline laeuft im Hintergrund.

    Wenn batch_id gesetzt ist, skippt die Pipeline die einzelne Narration -
    die gemeinsame Narration wird stattdessen vom Batch-Monitor generiert,
    sobald alle Jobs des Batches fertig sind.
    """
    job_id = uuid.uuid4().hex[:12]
    await _update_job(
        job_id,
        id=job_id,
        pokemon_a=pokemon_a,
        pokemon_b=pokemon_b,
        concept=concept,
        tone_hint=tone_hint,
        batch_id=batch_id,
        status="queued",
        current_step="queued",
        error=None,
        output_dir=None,
        variants=[],
        created_at=_now_iso(),
    )
    _register_task(job_id, asyncio.create_task(_run_fusion(job_id)))
    return job_id


async def submit_batch(ideas: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Queued mehrere Fusionen als Batch. Am Ende wird eine gemeinsame
    DE+EN Narration generiert, die alle Fusionen in einem Fluss abdeckt.
    Gibt (batch_id, job_ids) zurueck.
    """
    if not ideas:
        raise ValueError("Keine Ideen im Batch.")
    batch_id = "batch_" + uuid.uuid4().hex[:10]
    job_ids: list[str] = []
    for idea in ideas:
        jid = await submit_fusion(
            pokemon_a=str(idea.get("pokemon_a", "")).strip(),
            pokemon_b=str(idea.get("pokemon_b", "")).strip(),
            concept=str(idea.get("concept", "")).strip(),
            tone_hint=idea.get("tone_hint"),
            batch_id=batch_id,
        )
        job_ids.append(jid)

    await _update_batch(
        batch_id,
        id=batch_id,
        job_ids=job_ids,
        status="running",
        narration_de=None,
        narration_en=None,
        narration_path=None,
        error=None,
        created_at=_now_iso(),
    )
    _register_task(f"batch:{batch_id}", asyncio.create_task(_run_batch_monitor(batch_id)))
    return batch_id, job_ids


async def _run_batch_monitor(batch_id: str) -> None:
    """Wartet bis alle Jobs des Batches done/error sind, dann generiert
    die gemeinsame Narration."""
    try:
        # Warte auf alle Jobs (Poll-Intervall 5s, max 4h)
        deadline = time.time() + 4 * 3600
        job_ids: list[str] = []
        while True:
            if time.time() > deadline:
                raise RuntimeError("Batch-Monitor-Timeout (4h).")
            batch = await get_batch(batch_id)
            if not batch:
                return
            job_ids = batch.get("job_ids") or []
            statuses = []
            for jid in job_ids:
                j = await get_job(jid)
                statuses.append((j or {}).get("status"))
            if statuses and all(s in ("done", "error") for s in statuses):
                break
            await asyncio.sleep(5)

        # Sammle done-Fusionen mit ihren Meta-Daten
        fusions_for_narration: list[dict[str, str]] = []
        for jid in job_ids:
            j = await get_job(jid)
            if not j or j.get("status") != "done":
                continue
            out_dir_rel = j.get("output_dir")
            if not out_dir_rel:
                continue
            meta_path = PROJECT_ROOT / out_dir_rel / "_meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fusions_for_narration.append({
                "pokemon_a": meta.get("pokemon_a", ""),
                "pokemon_b": meta.get("pokemon_b", ""),
                "pokemon_a_de": meta.get("pokemon_a_de", meta.get("pokemon_a", "")),
                "pokemon_b_de": meta.get("pokemon_b_de", meta.get("pokemon_b", "")),
                "distinctive_traits": meta.get("distinctive_traits", ""),
                "step5_transformation": meta.get("step5_transformation", ""),
                "step6_showcase": meta.get("step6_showcase", ""),
                "showcase_image_prompt": meta.get("showcase_image_prompt", ""),
            })

        if not fusions_for_narration:
            await _update_batch(
                batch_id,
                status="error",
                error="Keine abgeschlossene Fusion im Batch - keine Narration moeglich.",
            )
            return

        await _update_batch(batch_id, status="generating_narration")
        narration_de, narration_en = await openai_client.generate_batch_narration(
            fusions_for_narration
        )

        # Suno-Prompt fuer Background-Music
        traits_summary = " | ".join(
            (f.get("distinctive_traits") or "")[:200]
            for f in fusions_for_narration
        )[:1500]
        suno_prompt = await openai_client.generate_suno_prompt(
            narration_en,
            fusion_count=len(fusions_for_narration),
            overall_tone=traits_summary or "cinematic epic, hauntingly majestic",
        )

        # YouTube Shorts SEO
        yt_title, yt_description = await openai_client.generate_yt_seo(
            narration_en,
            fusions=fusions_for_narration,
            overall_tone=traits_summary or "cinematic epic, hauntingly majestic",
        )

        # Narration + Suno + YT-Datei schreiben
        batch_dir = OUTPUT_DIR / "batches"
        batch_dir.mkdir(parents=True, exist_ok=True)
        md_path = batch_dir / f"{batch_id}_narration.md"
        fusion_list = "\n".join(
            f"- {f['pokemon_a']} x {f['pokemon_b']}" for f in fusions_for_narration
        )
        md = (
            f"# Batch Narration - {batch_id}\n\n"
            f"> Durchgehende DE + EN Narration fuer eine Fusion-Compilation.\n\n"
            f"Fusionen in Reihenfolge:\n{fusion_list}\n\n"
            f"---\n\n## Deutsch\n\n{narration_de}\n\n"
            f"---\n\n## English\n\n{narration_en}\n\n"
            f"---\n\n## Suno Background Music Prompt\n\n{suno_prompt}\n\n"
            f"---\n\n## YouTube Shorts SEO\n\n"
            f"**Title:** {yt_title}\n\n"
            f"**Description:**\n\n{yt_description}\n"
        )
        md_path.write_text(md, encoding="utf-8")

        await _update_batch(
            batch_id,
            status="done",
            narration_de=narration_de,
            narration_en=narration_en,
            suno_prompt=suno_prompt,
            yt_title=yt_title,
            yt_description=yt_description,
            narration_path=_relative_to_root(md_path),
            fusion_count=len(fusions_for_narration),
        )
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        await _update_batch(batch_id, status="error", error=err)


async def rerun_batch(batch_id: str) -> tuple[str, list[str]]:
    """Rerun failed jobs eines Batches. Erfolgreiche Fusionen bleiben,
    fuer jeden failed Job wird ein neuer Job-Submit gemacht (gleiche
    Pokemon / tone_hint / batch_id). batch.job_ids wird aktualisiert,
    Narration-State resettet, Monitor neu gestartet.

    Gibt (batch_id, new_job_ids) zurueck.
    """
    batch = await get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} nicht gefunden")

    old_ids: list[str] = batch.get("job_ids") or []
    keep_ids: list[str] = []
    failed_jobs: list[dict[str, Any]] = []
    for jid in old_ids:
        j = await get_job(jid)
        if not j:
            continue
        # Auch cancelled jobs werden als rerunnable behandelt - nicht nur error
        if j.get("status") in ("error", "cancelled"):
            failed_jobs.append(j)
        else:
            keep_ids.append(jid)

    if not failed_jobs:
        raise ValueError(
            "Keine fehlgeschlagenen oder abgebrochenen Jobs im Batch - nichts zu rerunnen."
        )

    new_ids: list[str] = []
    for j in failed_jobs:
        new_jid = await submit_fusion(
            pokemon_a=j.get("pokemon_a", ""),
            pokemon_b=j.get("pokemon_b", ""),
            concept=j.get("concept", "") or "",
            tone_hint=j.get("tone_hint"),
            batch_id=batch_id,
        )
        new_ids.append(new_jid)

    await _update_batch(
        batch_id,
        job_ids=keep_ids + new_ids,
        status="running",
        error=None,
        narration_de=None,
        narration_en=None,
        narration_path=None,
    )
    _register_task(f"batch:{batch_id}", asyncio.create_task(_run_batch_monitor(batch_id)))
    return batch_id, new_ids


async def rerun_job(
    job_id: str,
    pokemon_a: str | None = None,
    pokemon_b: str | None = None,
) -> str:
    """Rerun eines einzelnen Jobs (status=error oder cancelled).
    Erstellt einen neuen Job mit gleichen Parametern (pokemon_a/b,
    concept, tone_hint, batch_id). Falls der Job zu einem Batch gehoert,
    wird seine ID im batch.job_ids durch die neue ersetzt und der
    Batch-Monitor neu angestossen (Narration + Suno + YT-SEO werden
    resettet, weil der Compilation-Output nach Abschluss neu generiert
    werden muss).

    pokemon_a / pokemon_b: Wenn gesetzt, ueberschreiben sie die Namen vom
    Original-Job. Das ist nuetzlich wenn ein Pokemon-Name im PokeAPI nicht
    aufgeloest werden konnte (z.B. Tippfehler "Charizrad") - statt einen
    komplett neuen Pipeline-Run mit verlorenem Batch-Kontext zu starten,
    kann der User den Namen direkt am gefailten Job korrigieren und die
    bestehende Batch-Mitgliedschaft bleibt erhalten.

    Gibt neue job_id zurueck.
    """
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") not in ("error", "cancelled"):
        raise ValueError(
            f"Rerun nur fuer Status 'error' oder 'cancelled' moeglich "
            f"(aktuell: {job.get('status')!r})"
        )

    new_a = (pokemon_a or "").strip() or job.get("pokemon_a", "")
    new_b = (pokemon_b or "").strip() or job.get("pokemon_b", "")
    if not new_a or not new_b:
        raise ValueError("pokemon_a und pokemon_b duerfen nicht leer sein.")

    new_jid = await submit_fusion(
        pokemon_a=new_a,
        pokemon_b=new_b,
        concept=job.get("concept", "") or "",
        tone_hint=job.get("tone_hint"),
        batch_id=job.get("batch_id"),
    )

    batch_id = job.get("batch_id")
    if batch_id:
        batch = await get_batch(batch_id)
        if batch:
            new_job_ids = [
                new_jid if jid == job_id else jid
                for jid in batch.get("job_ids") or []
            ]
            await _update_batch(
                batch_id,
                job_ids=new_job_ids,
                status="running",
                error=None,
                narration_de=None,
                narration_en=None,
                narration_path=None,
                suno_prompt=None,
                yt_title=None,
                yt_description=None,
            )
            _register_task(
                f"batch:{batch_id}",
                asyncio.create_task(_run_batch_monitor(batch_id)),
            )
    return new_jid


async def regenerate_variant(job_id: str, variant_index: int) -> None:
    """Regeneriert EINE Step-4-Variante. Nutzt gleiches Distinctive-Traits."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Regenerate nur erlaubt, wenn Job bereits 'done' ist.")
    # 1-8: STEP4_VARIANTS + 5 extra Slots (analog zu set_favorite / upload-variants)
    if not (1 <= variant_index <= STEP4_VARIANTS + 5):
        raise ValueError(
            f"variant_index muss zwischen 1 und {STEP4_VARIANTS + 5} liegen"
        )

    _register_task(job_id, asyncio.create_task(_run_regenerate(job_id, variant_index)))


async def regenerate_all_variants(job_id: str, design_mode: str | None = None) -> None:
    """Regeneriert ALLE Step-4-Varianten neu (wenn keine gefaellt).

    Nutzt dieselben Referenzen + Distinctive-Traits, schreibt die 5
    Variant-Dateien komplett neu. Favorit, Showcase-Bilder und Showcase-
    Pick werden resettet weil die alten Bilder weg sind.

    design_mode: 'blend' / 'unique' / None. Wenn None, wird der globale
    settings.step4_design_mode verwendet. Sonst override fuer DIESEN run.
    """
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Regenerate-All nur erlaubt, wenn Job bereits 'done' ist.")
    if design_mode is not None and design_mode not in ("blend", "unique"):
        raise ValueError("design_mode muss 'blend', 'unique' oder null sein.")
    _register_task(
        job_id,
        asyncio.create_task(_run_regenerate_all(job_id, design_mode=design_mode)),
    )


async def regenerate_all_variants_custom(job_id: str, custom_prompt: str) -> None:
    """Regeneriert ALLE Step-4-Varianten mit einem User-bereitgestellten Prompt.

    Statt Default-Step-4 mit Distinctive-Traits wird der Prompt 1:1
    verwendet. References (signature_bg, step2a, step2b) bleiben gleich.
    Favorit + Showcase-Pick werden resettet.
    """
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Custom-Regenerate nur erlaubt, wenn Job bereits 'done' ist.")
    if not (custom_prompt or "").strip():
        raise ValueError("Custom-Prompt darf nicht leer sein.")
    _register_task(
        job_id,
        asyncio.create_task(_run_regenerate_all(job_id, custom_prompt=custom_prompt.strip())),
    )


async def _run_regenerate_all(
    job_id: str,
    custom_prompt: str | None = None,
    design_mode: str | None = None,
) -> None:
    async with _FUSION_SEMAPHORE:
        try:
            await _update_job(
                job_id,
                status="running",
                current_step="step_4_fusion_variants",
                error=None,
                favorite_variant=None,
                showcase_variants=[],
                showcase_pick=None,
                showcase_status=None,
                showcase_error=None,
            )
            job = await get_job(job_id)
            assert job is not None
            out_dir = PROJECT_ROOT / job["output_dir"]
            meta_path = out_dir / "_meta.json"
            if not meta_path.exists():
                raise RuntimeError("_meta.json fehlt, Regenerate-All nicht moeglich.")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pokemon_a = meta["pokemon_a"]
            pokemon_b = meta["pokemon_b"]
            distinctive_traits = meta["distinctive_traits"]
            step2a_out = out_dir / meta["files"]["step_2a"]
            step2b_out = out_dir / meta["files"]["step_2b"]

            if custom_prompt:
                step4_prompt = custom_prompt
                # Speichere den Custom-Prompt in meta damit er sichtbar ist
                meta["last_custom_prompt"] = custom_prompt
                meta_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            else:
                effective_mode = design_mode or settings.step4_design_mode
                step4_prompt = (
                    prompts.STEP4_FUSION_DESIGN_TEMPLATES.get(
                        effective_mode,
                        prompts.STEP4_FUSION_DESIGN_BLEND,
                    )
                    .replace("{POKEMON_A}", pokemon_a)
                    .replace("{POKEMON_B}", pokemon_b)
                    .replace("{DISTINCTIVE_TRAITS}", distinctive_traits)
                )

            variant_tasks = []
            variant_paths: list[Path] = []
            for i in range(1, STEP4_VARIANTS + 1):
                vpath = out_dir / f"04_fusion_v{i}.png"
                variant_paths.append(vpath)
                variant_tasks.append(
                    aiauto_client.generate_image(
                        step4_prompt, vpath,
                        reference_images=[
                            SIGNATURE_BACKGROUND_PATH, step2a_out, step2b_out,
                        ],
                    )
                )
            # return_exceptions=True: partial success darf als done gelten.
            # AI-Auto/Cloudflare hat manchmal RemoteProtocolError mid-stream;
            # wir wollen nicht 2 erfolgreiche Bilder wegwerfen wegen 1 fail.
            results = await asyncio.gather(*variant_tasks, return_exceptions=True)
            success_paths: list[Path] = []
            errors: list[str] = []
            for i, res in enumerate(results):
                if isinstance(res, BaseException):
                    errors.append(f"v{i+1}: {type(res).__name__}: {res}")
                else:
                    success_paths.append(variant_paths[i])
            if not success_paths:
                raise RuntimeError("Alle Varianten fehlgeschlagen: " + " | ".join(errors))

            await _update_job(
                job_id,
                status="done",
                current_step="done",
                variants=[_relative_to_root(p) for p in success_paths],
                error=" | ".join(errors) if errors else None,
            )
        except asyncio.CancelledError:
            await _update_job(
                job_id,
                status="cancelled",
                current_step="cancelled",
                error="Regenerate-All wurde abgebrochen.",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            await _update_job(job_id, status="error", current_step="error", error=err)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def cancel_job(job_id: str) -> bool:
    """Bricht einen laufenden Job ab. Gibt True zurueck wenn ein Task
    cancelled wurde, False wenn kein laufender Task bekannt war."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") not in ("running", "queued"):
        raise ValueError(
            f"Job ist bereits im Zustand '{job.get('status')}' - nichts zu canceln."
        )
    task = _TASKS.get(job_id)
    showcase_task = _TASKS.get(f"showcase:{job_id}")
    cancelled = False
    if task and not task.done():
        task.cancel()
        cancelled = True
    if showcase_task and not showcase_task.done():
        showcase_task.cancel()
        cancelled = True
    if not cancelled:
        # Kein aktiver Task, aber State sagt running - direkt aufraeumen
        await _update_job(
            job_id,
            status="cancelled",
            current_step="cancelled",
            error="Manuell abgebrochen (kein aktiver Task gefunden).",
        )
    return cancelled


async def cancel_batch(batch_id: str) -> int:
    """Bricht alle laufenden Jobs eines Batches + den Monitor ab.
    Gibt Anzahl der abgebrochenen Jobs zurueck."""
    batch = await get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} nicht gefunden")
    count = 0
    monitor = _TASKS.get(f"batch:{batch_id}")
    if monitor and not monitor.done():
        monitor.cancel()
    for jid in batch.get("job_ids") or []:
        j = await get_job(jid)
        if not j or j.get("status") not in ("running", "queued"):
            continue
        try:
            if await cancel_job(jid):
                count += 1
            else:
                count += 1  # auch wenn kein task da war, state wurde aufgeraeumt
        except ValueError:
            pass
    await _update_batch(
        batch_id,
        status="cancelled",
        error=f"Batch manuell abgebrochen ({count} Job(s) gestoppt).",
    )
    return count


CHECKLIST_KEYS = {"step5", "step6a", "step6b", "narration", "suno", "youtube", "editing"}


async def set_favorite(job_id: str, variant: int | None) -> None:
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    # 1-8 erlaubt: STEP4_VARIANTS (=3 Standard-Varianten) + bis zu 5 extra
    # Slots aus Regenerate / Manual-Upload. Validation lokal hier, weil
    # set_favorite frueher hardcoded auf 1..3 begrenzt war und damit alle
    # manuell hochgeladenen v4 / v5 nicht-fav-bar gewesen sind.
    if variant is not None and not (1 <= variant <= STEP4_VARIANTS + 5):
        raise ValueError(
            f"variant muss zwischen 1 und {STEP4_VARIANTS + 5} sein oder null"
        )
    await _update_job(job_id, favorite_variant=variant)


async def generate_showcase_images(
    job_id: str, prompt_override: str | None = None,
) -> None:
    """Generiert SHOWCASE_VARIANTS (default 4) statische Showcase-Composition-
    Images als Blueprint-Kandidaten fuer den Kling-Elements-Fallback (Step 7).

    Nutzt die Favoriten-Fusion-Variante als Reference und den Showcase-Image-
    Prompt aus meta (bzw. prompt_override falls vom User gesetzt), rendert
    in 16:9.
    """
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Showcase-Generation nur fuer abgeschlossene Jobs erlaubt.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v5).")
    if job.get("showcase_status") == "running":
        raise ValueError("Showcase-Generation laeuft bereits fuer diesen Job.")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt - Job-Output unvollstaendig.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if prompt_override and prompt_override.strip():
        image_prompt = prompt_override.strip()
    else:
        # Bevorzuge den Static-Image-Prompt (gezielt fuer 1 Frame komponiert);
        # fallback auf step6_showcase fuer Backwards-Compat mit alten Jobs.
        image_prompt = meta.get("showcase_image_prompt") or meta.get("step6_showcase")
        if not image_prompt:
            raise RuntimeError("showcase_image_prompt / step6_showcase fehlt in _meta.json")
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path}")

    _register_task(
        f"showcase:{job_id}",
        asyncio.create_task(_run_showcase_generation(job_id, image_prompt, fav_path)),
    )


async def _run_showcase_generation(
    job_id: str, prompt: str, fav_path: Path
) -> None:
    try:
        await _update_job(
            job_id,
            showcase_status="running",
            showcase_error=None,
            showcase_variants=[],
        )
        job = await get_job(job_id)
        assert job is not None
        out_dir = PROJECT_ROOT / job["output_dir"]

        tasks = []
        paths: list[Path] = []
        for i in range(1, SHOWCASE_VARIANTS + 1):
            spath = out_dir / f"07_showcase_v{i}.png"
            paths.append(spath)
            tasks.append(
                aiauto_client.generate_image(
                    prompt, spath,
                    reference_images=[fav_path],
                    aspect_ratio="16:9",
                )
            )
        # return_exceptions=True: partial success ist OK fuer Showcase auch.
        sc_results = await asyncio.gather(*tasks, return_exceptions=True)
        sc_success_paths: list[Path] = []
        sc_errors: list[str] = []
        for i, res in enumerate(sc_results):
            if isinstance(res, BaseException):
                sc_errors.append(f"s{i+1}: {type(res).__name__}: {res}")
            else:
                sc_success_paths.append(paths[i])
        if not sc_success_paths:
            raise RuntimeError("Alle Showcase-Varianten fehlgeschlagen: " + " | ".join(sc_errors))

        await _update_job(
            job_id,
            showcase_status="done",
            showcase_error=" | ".join(sc_errors) if sc_errors else None,
            showcase_variants=[_relative_to_root(p) for p in sc_success_paths],
        )
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        await _update_job(job_id, showcase_status="error", showcase_error=err)


async def generate_step6_video(
    job_id: str, tries: int = 1, prompt_override: str | None = None,
) -> None:
    """Generiert das Step-6 Showcase-Video via Seedance 2 (AI-Auto).
    Nutzt step6_showcase prompt (oder prompt_override falls vom User
    gesetzt) + Favoriten-Variante als Reference.

    tries: 1-3 parallele Generations starten (jede in eigenen mp4-Slot).
    Nuetzlich weil Seedance gelegentlich fehlschlaegt - bei 3 Versuchen
    hat man meist mindestens 1-2 erfolgreiche Outputs.
    """
    tries = max(1, min(3, tries or 1))
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Step-6-Video nur fuer abgeschlossene Jobs.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v3).")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if prompt_override and prompt_override.strip():
        prompt = prompt_override.strip()
    else:
        prompt = meta.get("step6_showcase")
        if not prompt:
            raise RuntimeError("step6_showcase fehlt in _meta.json.")
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path}")

    await _spawn_video_slots(
        job_id, prompt, [fav_path], tries,
        list_field="step6_videos",
        filename_prefix="06_seedance_video",
    )


async def generate_action_scene_video(
    job_id: str, tries: int = 1, prompt_override: str | None = None,
) -> None:
    """Generiert das Action-Scene-Video via Seedance 2 (AI-Auto).
    Nutzt action_scene_prompt (oder prompt_override falls vom User
    gesetzt) + Favoriten-Variante als Reference.

    tries: 1-3 parallele Generations.
    """
    tries = max(1, min(3, tries or 1))
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Action-Scene-Video nur fuer abgeschlossene Jobs.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v3).")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if prompt_override and prompt_override.strip():
        prompt = prompt_override.strip()
    else:
        prompt = meta.get("action_scene_prompt")
        if not prompt:
            raise RuntimeError(
                "action_scene_prompt fehlt - bitte zuerst 'Generate Action Scene' im "
                "Next-Steps Panel klicken."
            )
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path}")

    await _spawn_video_slots(
        job_id, prompt, [fav_path], tries,
        list_field="action_scene_videos",
        filename_prefix="07_action_scene_video",
    )


async def generate_funny_scene_video(
    job_id: str, tries: int = 1, prompt_override: str | None = None,
) -> None:
    """Generiert das Funny-Scene-Video via Seedance 2 (AI-Auto).
    5-Sekunden One-Shot Comedy-Gag basierend auf der Anatomie / Element
    der Fusion. Nutzt funny_scene_prompt (oder prompt_override) +
    Favoriten-Variante als Reference.

    tries: 1-3 parallele Generations - Comedy-Beats sind hit-or-miss,
    multiple Tries lohnen sich.
    """
    tries = max(1, min(3, tries or 1))
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Funny-Scene-Video nur fuer abgeschlossene Jobs.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v3).")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if prompt_override and prompt_override.strip():
        prompt = prompt_override.strip()
    else:
        prompt = meta.get("funny_scene_prompt")
        if not prompt:
            raise RuntimeError(
                "funny_scene_prompt fehlt - bitte zuerst 'Generate Funny Scene' im "
                "Next-Steps Panel klicken."
            )
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path}")

    await _spawn_video_slots(
        job_id, prompt, [fav_path], tries,
        list_field="funny_scene_videos",
        filename_prefix="08_funny_scene_video",
        seconds=5,
    )


async def generate_fusion_sequence_video(
    job_id: str, tries: int = 1, prompt_override: str | None = None,
) -> None:
    """Step 5 Fusion-Sequence Video via Seedance 2 (AI-Auto).

    Generiert einen 5-Sekunden 4K Morph vom Start-Frame (beide Originale
    Side-by-Side) zur Favoriten-Fusion-Variante. Beide Bilder gehen als
    Reference-Ingredients zu Seedance.

    Default-Prompt = meta.step5_transformation (gleicher Prompt der auch
    fuer Kling First-Last-Frame manuell genutzt werden kann). Custom-Prompt
    via prompt_override.

    Output: 05_fusion_sequence_video_v{n}.mp4 in fusion_sequence_videos[].
    """
    tries = max(1, min(3, tries or 1))
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Fusion-Sequence-Video nur fuer abgeschlossene Jobs.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v3).")

    out_dir = PROJECT_ROOT / job["output_dir"]
    if prompt_override and prompt_override.strip():
        prompt = prompt_override.strip()
    else:
        prompt = prompts.STEP5_FUSION_SEQUENCE_DEFAULT

    start_frame = out_dir / "03_start_frame.png"
    if not start_frame.exists():
        raise RuntimeError(f"Start-Frame fehlt: {start_frame.name}")
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path.name}")

    split_ref = out_dir / "05_morph_split_ref.png"
    _build_fusion_morph_split_ref(start_frame, fav_path, split_ref)
    morph_prompt = _MORPH_SPLIT_PROMPT_LEGEND + prompt

    await _spawn_video_slots(
        job_id, morph_prompt, [split_ref], tries,
        list_field="fusion_sequence_videos",
        filename_prefix="05_fusion_sequence_video",
        seconds=5,
    )


async def generate_fusion_sequence_video_kling(
    job_id: str, tries: int = 1, prompt_override: str | None = None,
) -> None:
    """Step 5 Fusion-Sequence Video via Kling 2.5 Turbo Pro (AI-Auto).

    Alternative zum Seedance-Pfad: nutzt Kling als Video-Modell. Output
    landet in derselben fusion_sequence_videos-Liste mit Filename-Prefix
    `05_fusion_sequence_kling`, damit beide Modelle nebeneinander
    laufen koennen ohne sich zu ueberschreiben.

    Quality/Duration kommen aus den AIAUTO_KLING_* Settings (Default
    1080p/5s). Refs: gleiche Start-Frame + Favoriten-Variante wie bei
    Seedance.
    """
    from backend.config import settings as _settings  # local import

    tries = max(1, min(3, tries or 1))
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Fusion-Sequence-Video nur fuer abgeschlossene Jobs.")
    fav = job.get("favorite_variant")
    if not fav:
        raise ValueError("Bitte zuerst eine Favoriten-Variante markieren (Stern auf v1..v3).")

    out_dir = PROJECT_ROOT / job["output_dir"]
    if prompt_override and prompt_override.strip():
        prompt = prompt_override.strip()
    else:
        prompt = prompts.STEP5_FUSION_SEQUENCE_DEFAULT

    start_frame = out_dir / "03_start_frame.png"
    if not start_frame.exists():
        raise RuntimeError(f"Start-Frame fehlt: {start_frame.name}")
    fav_path = out_dir / f"04_fusion_v{fav}.png"
    if not fav_path.exists():
        raise RuntimeError(f"Favoriten-Datei fehlt: {fav_path.name}")

    split_ref = out_dir / "05_morph_split_ref.png"
    _build_fusion_morph_split_ref(start_frame, fav_path, split_ref)
    morph_prompt = _MORPH_SPLIT_PROMPT_LEGEND + prompt

    await _spawn_video_slots(
        job_id, morph_prompt, [split_ref], tries,
        list_field="fusion_sequence_videos",
        filename_prefix="05_fusion_sequence_kling",
        seconds=_settings.aiauto_kling_duration,
        video_model=_settings.aiauto_kling_model,
        aspect_ratio="9:16",
        resolution=_settings.aiauto_kling_quality,
    )


async def _spawn_video_slots(
    job_id: str,
    prompt: str,
    ref_paths: list[Path],
    tries: int,
    *,
    list_field: str,
    filename_prefix: str,
    seconds: int = 15,
    video_model: str | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "4k",
) -> None:
    """Startet `tries` parallele Video-Generations als neue Slots in der
    list_field-Liste des Jobs (append - bestehende Slots bleiben).

    `ref_paths` kann ein oder mehrere Bilder enthalten - mehrere Refs werden
    als Ingredients an Seedance gegeben (z.B. Start- + End-Frame fuer Morph).
    `seconds` steuert die Video-Laenge - Default 15s, Step-5 Transformation
    nutzt 5s, weil ein kurzer Morph reicht.

    `video_model` / `resolution` / `aspect_ratio` erlauben Kling-spezifische
    Overrides (z.B. model=kling_2_5_turbo_pro, resolution=1080p). None bei
    `video_model` faellt auf settings.aiauto_video_model (Seedance) zurueck.
    """
    job = await get_job(job_id)
    assert job is not None
    existing = list(job.get(list_field) or [])
    start_idx = len(existing)
    for i in range(tries):
        slot_idx = start_idx + i
        out_filename = f"{filename_prefix}_v{slot_idx + 1}.mp4"
        existing.append({
            "status": "queued",
            "path": None,
            "error": None,
            "filename": out_filename,
        })
    await _update_job(job_id, **{list_field: existing})

    for i in range(tries):
        slot_idx = start_idx + i
        out_filename = f"{filename_prefix}_v{slot_idx + 1}.mp4"
        task_key = f"{list_field}:{job_id}:{slot_idx}"
        _register_task(task_key, asyncio.create_task(
            _run_video_slot(
                job_id, prompt, ref_paths, slot_idx, out_filename, list_field, seconds,
                video_model=video_model, aspect_ratio=aspect_ratio, resolution=resolution,
            )
        ))


async def _update_video_slot(
    job_id: str, list_field: str, slot_idx: int, **patch: Any,
) -> None:
    async with _STATE_LOCK:
        state = await _load_state()
        job = state["jobs"].setdefault(job_id, {"id": job_id})
        videos = list(job.get(list_field) or [])
        while len(videos) <= slot_idx:
            videos.append({})
        slot = dict(videos[slot_idx] or {})
        slot.update(patch)
        videos[slot_idx] = slot
        job[list_field] = videos
        job["updated_at"] = _now_iso()
        await _save_state()


async def _run_video_slot(
    job_id: str,
    prompt: str,
    ref_paths: list[Path],
    slot_idx: int,
    out_filename: str,
    list_field: str,
    seconds: int = 15,
    *,
    video_model: str | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "4k",
) -> None:
    try:
        await _update_video_slot(
            job_id, list_field, slot_idx,
            status="running", error=None, filename=out_filename,
        )
        job = await get_job(job_id)
        assert job is not None
        out_dir = PROJECT_ROOT / job["output_dir"]
        video_out = out_dir / out_filename

        await aiauto_client.generate_video(
            prompt, video_out, reference_images=list(ref_paths),
            aspect_ratio=aspect_ratio, resolution=resolution, seconds=seconds,
            model=video_model,
        )
        await _update_video_slot(
            job_id, list_field, slot_idx,
            status="done", path=_relative_to_root(video_out), error=None,
        )
    except asyncio.CancelledError:
        await _update_video_slot(
            job_id, list_field, slot_idx,
            status="cancelled", error="Manuell abgebrochen.",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        await _update_video_slot(
            job_id, list_field, slot_idx,
            status="error", error=err,
        )


async def generate_action_scene(job_id: str) -> str:
    """Generiert einen Action-Scene-Prompt (pure motion / high-speed tracking
    fuer Seedance) fuer einen abgeschlossenen Job. On-demand, nicht in der
    Hauptpipeline. Speichert das Ergebnis in meta.action_scene_prompt und
    gibt den Prompt zurueck.
    """
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Action-Scene nur fuer abgeschlossene Jobs.")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    concept = meta.get("concept", "") or ""
    traits = meta.get("distinctive_traits", "")
    step6 = meta.get("step6_showcase", "")
    if not traits or not step6:
        raise RuntimeError("distinctive_traits oder step6_showcase fehlt.")

    prompt = await openai_client.generate_action_scene_prompt(
        pokemon_a, pokemon_b, concept, traits, step6,
    )

    # Persist in meta.json
    meta["action_scene_prompt"] = prompt
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    await _update_job(job_id, action_scene_prompt=prompt)
    return prompt


async def generate_funny_scene(job_id: str, gag_hint: str = "") -> str:
    """Generiert einen 5-Sekunden Funny-Scene Prompt fuer einen
    abgeschlossenen Job. On-demand, nicht in der Hauptpipeline.
    Speichert das Ergebnis in meta.funny_scene_prompt und gibt den
    Prompt zurueck. gag_hint optional - User-Input wenn der Gag in eine
    bestimmte Richtung gehen soll (z.B. 'fire fart', 'sneeze')."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Funny-Scene nur fuer abgeschlossene Jobs.")

    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    concept = meta.get("concept", "") or ""
    traits = meta.get("distinctive_traits", "")
    step6 = meta.get("step6_showcase", "")
    if not traits or not step6:
        raise RuntimeError("distinctive_traits oder step6_showcase fehlt.")

    prompt = await openai_client.generate_funny_scene_prompt(
        pokemon_a, pokemon_b, concept, traits, step6, gag_hint=gag_hint,
    )

    meta["funny_scene_prompt"] = prompt
    if gag_hint.strip():
        meta["funny_scene_gag_hint"] = gag_hint.strip()
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    await _update_job(job_id, funny_scene_prompt=prompt)
    return prompt


# ---------------------------------------------------------------------------
# Re-generate text prompts on-demand (Step 5 / Step 6 / Showcase Image)
# ---------------------------------------------------------------------------


async def _load_prompt_context(job_id: str) -> tuple[Path, dict[str, Any]]:
    """Common Setup fuer prompt-regen: laedt meta.json, validiert status."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Prompt-Regenerate nur fuer abgeschlossene Jobs.")
    out_dir = PROJECT_ROOT / job["output_dir"]
    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        raise RuntimeError("_meta.json fehlt.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta_path, meta


def _save_meta_field(meta_path: Path, meta: dict[str, Any], key: str, value: str) -> None:
    meta[key] = value
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def check_variant_eligibility(job_id: str, variant_index: int) -> dict[str, Any]:
    """Prueft eine Step-4-Variante via GPT-4o Vision auf Pokemon-IP-Risiko.
    Speichert Ergebnis in meta.eligibility[variant_index] und im Job-State."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if not (1 <= variant_index <= STEP4_VARIANTS + 5):
        raise ValueError(f"variant_index ungueltig: {variant_index}")

    out_dir = PROJECT_ROOT / job["output_dir"]
    variant_path = out_dir / f"04_fusion_v{variant_index}.png"
    if not variant_path.exists():
        raise RuntimeError(f"Variant-Datei fehlt: {variant_path}")

    img_bytes = variant_path.read_bytes()
    result = await openai_client.check_image_eligibility(img_bytes)

    # In meta.json persistieren
    meta_path = out_dir / "_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        elig = meta.get("eligibility") or {}
        elig[str(variant_index)] = result
        meta["eligibility"] = elig
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Auch im Job-State (damit Frontend ohne meta-fetch sieht)
    job_elig = dict(job.get("eligibility") or {})
    job_elig[str(variant_index)] = result
    await _update_job(job_id, eligibility=job_elig)

    return result


async def check_uploaded_image_eligibility(image_bytes: bytes) -> dict[str, Any]:
    """Prueft ein hochgeladenes Bild (z.B. von externer Quelle) auf
    Pokemon-IP-Risiko. Wird NICHT persistiert - reine ad-hoc Pruefung."""
    if not image_bytes:
        raise ValueError("Leeres Bild.")
    if len(image_bytes) > 15 * 1024 * 1024:
        raise ValueError("Bild zu gross (max 15 MB).")
    return await openai_client.check_image_eligibility(image_bytes)


async def generate_manual_video_prompts(image_bytes: bytes) -> dict[str, Any]:
    """Generiert ALLE Seedance / Kling Video-Prompts (Step 5 Transformation,
    Step 6 Showcase, Showcase Image, Action Scene) fuer ein hochgeladenes
    Creature-Bild ausserhalb der normalen Pipeline.

    Flow:
      1. Vision-Modell (Provider per Settings) zieht eine Distinctive-Traits-
         Beschreibung aus dem Bild.
      2. Mit dieser Beschreibung werden die 4 Text-Prompt-Generatoren
         parallel via GPT-4o gestartet (POKEMON_A/B leer - die Generatoren
         schreiben sowieso keine Pokemon-Namen ins Output).

    Wird NICHT persistiert - reine ad-hoc Generation. Returns dict mit:
      creature_description, step5_transformation, step6_showcase,
      showcase_image_prompt, action_scene
    Felder enthalten entweder den Prompt-String oder einen "error"-Wert
    wenn dieser einzelne Generator fehlschlug (partial-success).
    """
    if not image_bytes:
        raise ValueError("Leeres Bild.")
    if len(image_bytes) > 15 * 1024 * 1024:
        raise ValueError("Bild zu gross (max 15 MB).")

    description = await openai_client.describe_creature_image(image_bytes)

    # Step 6 zuerst, weil Showcase-Image + Action-Scene ihn als Referenz
    # einbauen. Step 5 laeuft parallel dazu.
    step5_task = asyncio.create_task(
        openai_client.generate_step5_transformation(
            pokemon_a="", pokemon_b="",
            concept="manual upload (no concept hook)",
            distinctive_traits=description,
        )
    )
    step6_task = asyncio.create_task(
        openai_client.generate_step6_showcase(
            pokemon_a="", pokemon_b="",
            concept="manual upload (no concept hook)",
            distinctive_traits=description,
        )
    )
    step5_res, step6_res = await asyncio.gather(
        step5_task, step6_task, return_exceptions=True,
    )

    step5_text = step5_res if isinstance(step5_res, str) else None
    step6_text = step6_res if isinstance(step6_res, str) else None
    # Fallback: wenn Step 6 selbst fehlschlug, verwende die description als
    # minimaler Kontext, damit Showcase-Image / Action-Scene nicht alle scheitern.
    step6_for_refs = step6_text or description

    showcase_task = asyncio.create_task(
        openai_client.generate_showcase_image_prompt(
            pokemon_a="", pokemon_b="",
            concept="manual upload (no concept hook)",
            distinctive_traits=description,
            step6_video_prompt=step6_for_refs,
        )
    )
    action_task = asyncio.create_task(
        openai_client.generate_action_scene_prompt(
            pokemon_a="", pokemon_b="",
            concept="manual upload (no concept hook)",
            distinctive_traits=description,
            step6_video_prompt=step6_for_refs,
        )
    )
    showcase_res, action_res = await asyncio.gather(
        showcase_task, action_task, return_exceptions=True,
    )

    def _coerce(value: Any) -> dict[str, str]:
        if isinstance(value, str):
            return {"prompt": value}
        return {"error": f"{type(value).__name__}: {value}"}

    return {
        "creature_description": description,
        "step5_transformation": _coerce(step5_res),
        "step6_showcase": _coerce(step6_res),
        "showcase_image_prompt": _coerce(showcase_res),
        "action_scene": _coerce(action_res),
    }


async def regenerate_narration(
    job_id: str, words_per_fusion: int | None = None,
) -> dict[str, Any]:
    """Regeneriert Narration (DE+EN) + Suno + YT-SEO fuer einen abgeschlossenen
    Single-Job. Schreibt _meta.json + narration.md neu und aktualisiert den
    Job-State. Funktioniert NICHT fuer Batch-Jobs - dort wird die gemeinsame
    Narration zentral am Batch geregenerated.

    words_per_fusion: optionaler Override fuer die Wortzahl der Beschreibung.
    None = settings.narration_words_per_fusion verwenden.

    Returns dict mit narration_de, narration_en, suno_prompt, yt_title,
    yt_description.
    """
    meta_path, meta = await _load_prompt_context(job_id)
    job = await get_job(job_id)
    assert job is not None
    if job.get("batch_id"):
        raise ValueError(
            "Dieser Job ist Teil eines Batches - benutze den Regenerate-"
            "Narration-Button am Batch-Panel (gemeinsame Compilation-Narration)."
        )

    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    pokemon_a_de = meta.get("pokemon_a_de", pokemon_a)
    pokemon_b_de = meta.get("pokemon_b_de", pokemon_b)
    distinctive_traits = meta.get("distinctive_traits", "")
    step5 = meta.get("step5_transformation", "")
    step6 = meta.get("step6_showcase", "")
    if not all([pokemon_a, pokemon_b, distinctive_traits, step5, step6]):
        raise RuntimeError(
            "Pflichtfelder in _meta.json fehlen (pokemon_a/b, distinctive_traits, "
            "step5_transformation, step6_showcase) - Narration kann nicht regenerated werden."
        )

    narration_de, narration_en = await openai_client.generate_narration(
        pokemon_a, pokemon_b, pokemon_a_de, pokemon_b_de,
        distinctive_traits, step5, step6,
        words_per_fusion=words_per_fusion,
    )
    suno_prompt = await openai_client.generate_suno_prompt(
        narration_en,
        fusion_count=1,
        overall_tone=distinctive_traits,
    )
    yt_title, yt_description = await openai_client.generate_yt_seo(
        narration_en,
        fusions=[{"pokemon_a": pokemon_a, "pokemon_b": pokemon_b}],
        overall_tone=distinctive_traits,
    )

    meta["narration_de"] = narration_de
    meta["narration_en"] = narration_en
    meta["suno_prompt"] = suno_prompt
    meta["yt_title"] = yt_title
    meta["yt_description"] = yt_description
    if words_per_fusion is not None:
        meta["narration_words_per_fusion"] = int(words_per_fusion)
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    out_dir = meta_path.parent
    _write_narration_md(
        out_dir, narration_de, narration_en, suno_prompt,
        yt_title=yt_title, yt_description=yt_description,
    )

    files = dict(job.get("files") or {})
    files["narration_md"] = _relative_to_root(out_dir / "narration.md")
    await _update_job(
        job_id,
        narration_de=narration_de,
        narration_en=narration_en,
        suno_prompt=suno_prompt,
        yt_title=yt_title,
        yt_description=yt_description,
        files=files,
        narration_regen_at=_now_iso(),
    )
    return {
        "narration_de": narration_de,
        "narration_en": narration_en,
        "suno_prompt": suno_prompt,
        "yt_title": yt_title,
        "yt_description": yt_description,
    }


async def regenerate_batch_narration(
    batch_id: str, words_per_fusion: int | None = None,
) -> dict[str, Any]:
    """Regeneriert die gemeinsame Compilation-Narration (DE+EN) + Suno + YT-SEO
    fuer einen Batch. Sammelt die fertigen Fusionen erneut aus deren _meta.json
    und ueberschreibt das Batch-narration.md.

    words_per_fusion: optionaler Override fuer die Wortzahl pro Fusion.
    None = settings.narration_words_per_fusion verwenden.

    Returns dict mit narration_de, narration_en, suno_prompt, yt_title,
    yt_description.
    """
    batch = await get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} nicht gefunden")

    job_ids: list[str] = batch.get("job_ids") or []
    fusions_for_narration: list[dict[str, str]] = []
    for jid in job_ids:
        j = await get_job(jid)
        if not j or j.get("status") != "done":
            continue
        out_dir_rel = j.get("output_dir")
        if not out_dir_rel:
            continue
        meta_path = PROJECT_ROOT / out_dir_rel / "_meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fusions_for_narration.append({
            "pokemon_a": meta.get("pokemon_a", ""),
            "pokemon_b": meta.get("pokemon_b", ""),
            "pokemon_a_de": meta.get("pokemon_a_de", meta.get("pokemon_a", "")),
            "pokemon_b_de": meta.get("pokemon_b_de", meta.get("pokemon_b", "")),
            "distinctive_traits": meta.get("distinctive_traits", ""),
            "step5_transformation": meta.get("step5_transformation", ""),
            "step6_showcase": meta.get("step6_showcase", ""),
        })
    if not fusions_for_narration:
        raise ValueError(
            "Keine abgeschlossene Fusion im Batch - keine Narration moeglich."
        )

    narration_de, narration_en = await openai_client.generate_batch_narration(
        fusions_for_narration,
        words_per_fusion=words_per_fusion,
    )
    traits_summary = " | ".join(
        (f.get("distinctive_traits") or "")[:200]
        for f in fusions_for_narration
    )[:1500]
    suno_prompt = await openai_client.generate_suno_prompt(
        narration_en,
        fusion_count=len(fusions_for_narration),
        overall_tone=traits_summary or "cinematic epic, hauntingly majestic",
    )
    yt_title, yt_description = await openai_client.generate_yt_seo(
        narration_en,
        fusions=fusions_for_narration,
        overall_tone=traits_summary or "cinematic epic, hauntingly majestic",
    )

    batch_dir = OUTPUT_DIR / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    md_path = batch_dir / f"{batch_id}_narration.md"
    fusion_list = "\n".join(
        f"- {f['pokemon_a']} x {f['pokemon_b']}" for f in fusions_for_narration
    )
    md = (
        f"# Batch Narration - {batch_id}\n\n"
        f"> Durchgehende DE + EN Narration fuer eine Fusion-Compilation.\n\n"
        f"Fusionen in Reihenfolge:\n{fusion_list}\n\n"
        f"---\n\n## Deutsch\n\n{narration_de}\n\n"
        f"---\n\n## English\n\n{narration_en}\n\n"
        f"---\n\n## Suno Background Music Prompt\n\n{suno_prompt}\n\n"
        f"---\n\n## YouTube Shorts SEO\n\n"
        f"**Title:** {yt_title}\n\n"
        f"**Description:**\n\n{yt_description}\n"
    )
    md_path.write_text(md, encoding="utf-8")

    patch: dict[str, Any] = {
        "status": "done",
        "narration_de": narration_de,
        "narration_en": narration_en,
        "suno_prompt": suno_prompt,
        "yt_title": yt_title,
        "yt_description": yt_description,
        "narration_path": _relative_to_root(md_path),
        "fusion_count": len(fusions_for_narration),
        "narration_regen_at": _now_iso(),
    }
    if words_per_fusion is not None:
        patch["narration_words_per_fusion"] = int(words_per_fusion)
    await _update_batch(batch_id, **patch)
    return {
        "narration_de": narration_de,
        "narration_en": narration_en,
        "suno_prompt": suno_prompt,
        "yt_title": yt_title,
        "yt_description": yt_description,
    }


async def regenerate_step5_prompt(job_id: str) -> str:
    """Regeneriert den Step-5 Transformation-Prompt (Kling) ohne Bilder
    neu zu generieren. Speichert in meta.step5_transformation."""
    meta_path, meta = await _load_prompt_context(job_id)
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    concept = meta.get("concept", "") or ""
    traits = meta.get("distinctive_traits", "")
    if not traits:
        raise RuntimeError("distinctive_traits fehlt.")

    prompt = await openai_client.generate_step5_transformation(
        pokemon_a, pokemon_b, concept, traits,
    )
    _save_meta_field(meta_path, meta, "step5_transformation", prompt)
    await _update_job(job_id, step5_prompt_regen_at=_now_iso())
    return prompt


async def regenerate_step6_prompt(job_id: str) -> str:
    """Regeneriert den Step-6 Showcase-Prompt (Seedance / Kling Elements
    5-Cut) ohne Bilder neu zu generieren. Speichert in meta.step6_showcase."""
    meta_path, meta = await _load_prompt_context(job_id)
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    concept = meta.get("concept", "") or ""
    traits = meta.get("distinctive_traits", "")
    if not traits:
        raise RuntimeError("distinctive_traits fehlt.")

    prompt = await openai_client.generate_step6_showcase(
        pokemon_a, pokemon_b, concept, traits,
    )
    _save_meta_field(meta_path, meta, "step6_showcase", prompt)
    await _update_job(job_id, step6_prompt_regen_at=_now_iso())
    return prompt


async def regenerate_showcase_image_prompt(job_id: str) -> str:
    """Regeneriert den Static Showcase Image Prompt (Kling Elements
    @image2 / Flow Blueprint). Speichert in meta.showcase_image_prompt."""
    meta_path, meta = await _load_prompt_context(job_id)
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    concept = meta.get("concept", "") or ""
    traits = meta.get("distinctive_traits", "")
    step6 = meta.get("step6_showcase", "")
    if not traits or not step6:
        raise RuntimeError(
            "distinctive_traits oder step6_showcase fehlt - regenerate Step 6 zuerst."
        )

    prompt = await openai_client.generate_showcase_image_prompt(
        pokemon_a, pokemon_b, concept, traits, step6,
    )
    _save_meta_field(meta_path, meta, "showcase_image_prompt", prompt)
    await _update_job(job_id, showcase_image_prompt_regen_at=_now_iso())
    return prompt


async def regenerate_start_frame(job_id: str) -> str:
    """Regeneriert den Step-3 Start-Frame (03_start_frame.png) - das
    'beide Pokemon Seite an Seite auf dem Sockel'-Bild.

    Nutzt die bestehenden Step-2A/2B Realistic-Singles + Signature-Background
    als Refs. Size-Hint wird neu aus den PokeAPI-Hoehen berechnet (Cache).

    Returns: relative path to 03_start_frame.png.
    """
    meta_path, meta = await _load_prompt_context(job_id)
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    if not pokemon_a or not pokemon_b:
        raise RuntimeError("pokemon_a / pokemon_b fehlen in _meta.json.")

    out_dir = meta_path.parent
    files = meta.get("files") or {}
    step2a_rel = files.get("step_2a")
    step2b_rel = files.get("step_2b")
    if not step2a_rel or not step2b_rel:
        raise RuntimeError("step_2a / step_2b Files fehlen in meta.files.")
    step2a_out = out_dir / step2a_rel
    step2b_out = out_dir / step2b_rel
    if not step2a_out.exists() or not step2b_out.exists():
        raise RuntimeError(
            f"Realistic-Singles fehlen ({step2a_out.name} / {step2b_out.name}) - "
            "kann Start-Frame ohne sie nicht regenerieren."
        )

    # Size-Hint analog zur _pipeline-Logik (Hoehen via PokeAPI-Cache).
    height_a, height_b = await asyncio.gather(
        pokemon_refs.get_pokemon_height_m(pokemon_a),
        pokemon_refs.get_pokemon_height_m(pokemon_b),
    )
    size_hint = "Maintain canonical body-size proportions between both Pokemon."
    if height_a and height_b and height_a > 0 and height_b > 0:
        ratio = max(height_a, height_b) / min(height_a, height_b)
        if ratio >= 1.5:
            if height_a >= height_b:
                bigger, smaller = pokemon_a, pokemon_b
                bigger_h, smaller_h = height_a, height_b
            else:
                bigger, smaller = pokemon_b, pokemon_a
                bigger_h, smaller_h = height_b, height_a
            size_hint = (
                f"Important: {bigger} is canonically much larger than {smaller} "
                f"({bigger}: ~{bigger_h:.1f}m tall, {smaller}: ~{smaller_h:.1f}m tall, "
                f"a {ratio:.1f}x size difference). This proportion MUST be visible "
                f"in the frame - {bigger} towers over {smaller}."
            )

    step3_out = out_dir / "03_start_frame.png"
    step3_prompt = (
        prompts.STEP3_START_FRAME
        .replace("{POKEMON_A}", pokemon_a)
        .replace("{POKEMON_B}", pokemon_b)
        .replace("{SIZE_HINT}", size_hint)
        .strip()
    )
    await aiauto_client.generate_image(
        step3_prompt,
        step3_out,
        reference_images=[SIGNATURE_BACKGROUND_PATH, step2a_out, step2b_out],
    )

    await _update_job(job_id, start_frame_regen_at=_now_iso())
    return _relative_to_root(step3_out)


async def regenerate_realistic_singles(
    job_id: str,
    which: str = "both",
) -> dict[str, str]:
    """Regeneriert die Step-2A / Step-2B Realistic-Singles fuer einen
    abgeschlossenen Job - bypasst den Per-Pokemon Cache und schreibt
    die neuen Bilder sowohl in den Job-Output-Folder als auch zurueck
    in den Cache (sodass nachfolgende Fusionen mit dem gleichen Pokemon
    die neue Version benutzen).

    `which`: 'both' (default) | 'a' | 'b' - welche Singles regeneriert
    werden sollen.

    Returns: {step_2a?: rel-path, step_2b?: rel-path}.
    """
    if which not in ("both", "a", "b"):
        raise ValueError(f"which muss 'both' / 'a' / 'b' sein, war {which!r}")

    meta_path, meta = await _load_prompt_context(job_id)
    pokemon_a = meta.get("pokemon_a", "")
    pokemon_b = meta.get("pokemon_b", "")
    if not pokemon_a or not pokemon_b:
        raise RuntimeError("pokemon_a / pokemon_b fehlen in _meta.json.")

    out_dir = meta_path.parent
    files = dict(meta.get("files") or {})

    # Targets bestimmen
    targets: list[tuple[str, str, str]] = []  # (pokemon, files-key, filename)
    step2a_rel = files.get("step_2a") or f"02a_realistic_{_folder_slug(pokemon_a)}.png"
    step2b_rel = files.get("step_2b") or f"02b_realistic_{_folder_slug(pokemon_b)}.png"
    if which in ("both", "a"):
        targets.append((pokemon_a, "step_2a", step2a_rel))
    if which in ("both", "b"):
        targets.append((pokemon_b, "step_2b", step2b_rel))

    # PokeAPI-Refs frisch holen (oder aus cache - get_official_artwork ist gecached)
    ref_paths: dict[str, Path] = {}
    for pokemon, _, _ in targets:
        ref_paths[pokemon] = await pokemon_refs.fetch_official_artwork(pokemon)

    # Cache invalidieren BEVOR wir neu generieren - sonst koennte ein
    # paralleler Job die alte cached Datei greifen waehrend wir neu rendern.
    for pokemon, _, _ in targets:
        cache_path = _realistic_cache_path(pokemon)
        if cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass

    # Parallel rendern + in Cache zurueckschreiben
    out_paths: dict[str, Path] = {}
    tasks = []
    for pokemon, key, fname in targets:
        out_path = out_dir / fname
        out_paths[key] = out_path
        # _step2_realistic_cached weiss Cache wieder schreiben sobald die
        # Generation durch ist - wir nutzen die normale Function damit
        # nachfolgende Fusionen auch den frischen Render benutzen.
        tasks.append(_step2_realistic_cached(
            pokemon, ref_paths[pokemon], out_path,
        ))
    await asyncio.gather(*tasks)

    # files-Map in meta + Job-State aktualisieren
    relative_map: dict[str, str] = {}
    for key, out_path in out_paths.items():
        files[key] = out_path.name
        relative_map[key] = _relative_to_root(out_path)
    meta["files"] = files
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Auch im Job-State files-Map updaten (damit Dashboard die neuen URLs sieht)
    job = await get_job(job_id)
    if job:
        job_files = dict(job.get("files") or {})
        job_files.update(relative_map)
        await _update_job(
            job_id,
            files=job_files,
            realistic_singles_regen_at=_now_iso(),
        )

    return relative_map


async def complete_with_manual_variants(
    job_id: str,
    variants: dict[int, bytes],
) -> dict[str, Any]:
    """Fallback fuer Jobs bei denen AI-Auto ein oder mehrere Step-4 Variants
    nicht zuverlaessig runtergeladen hat. Der User laedt sich die Bilder
    manuell aus der AI-Auto Web-UI runter und uploaded sie hier.

    Was die Funktion macht:
      1. Speichert die Bytes als 04_fusion_v{N}.png im Job-Output-Ordner.
      2. Falls Distinctive Traits noch nicht da: holt sie aus dem Job-State
         (Step 3 setzt sie schon, also normalerweise praesent) oder
         generiert sie frisch via GPT.
      3. Generiert step5_transformation, step6_showcase, showcase_image_prompt
         via GPT falls noch nicht in meta.
      4. Wenn der Job KEIN Batch-Member ist: Narration + Suno + YT-SEO mit.
      5. Schreibt _meta.json (mergt mit existierender) + video_prompts.md.
      6. Setzt status=done.

    Funktioniert sowohl fuer Jobs in 'error'-State (alle Variants
    fehlgeschlagen) als auch fuer 'done'-Jobs (zusaetzliche Variants
    nachschieben oder bestehende ueberschreiben).
    """
    if not variants:
        raise ValueError("Keine Variant-Bilder uebergeben.")
    for slot in variants:
        if not (1 <= slot <= 10):
            raise ValueError(f"Variant-Slot {slot} ausserhalb 1..10")

    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") == "running":
        raise ValueError("Job laeuft gerade - manuelle Variants nicht moeglich.")

    pokemon_a = job.get("pokemon_a", "")
    pokemon_b = job.get("pokemon_b", "")
    concept = job.get("concept") or f"A cinematic fusion of {pokemon_a} and {pokemon_b}."
    tone_hint = job.get("tone_hint")
    if not pokemon_a or not pokemon_b:
        raise RuntimeError("pokemon_a / pokemon_b fehlen im Job-State.")

    # Output-Ordner. Bei manchen alten error-Jobs kann der noch nicht existieren -
    # dann legen wir ihn jetzt an (gleicher Algo wie der reguläre Pipeline-Path).
    out_dir_rel = job.get("output_dir")
    if out_dir_rel:
        out_dir = PROJECT_ROOT / out_dir_rel
    else:
        out_dir = _make_output_dir(pokemon_a, pokemon_b)
        await _update_job(job_id, output_dir=_relative_to_root(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Variants auf Disk schreiben
    saved_paths: list[Path] = []
    for slot in sorted(variants):
        vpath = out_dir / f"04_fusion_v{slot}.png"
        vpath.write_bytes(variants[slot])
        saved_paths.append(vpath)
        log.info("manual variant uploaded: %s (%d bytes)", vpath.name, len(variants[slot]))

    # 2) Existing meta laden (falls Pipeline bis vor Step 4 lief) oder leeres dict.
    meta_path = out_dir / "_meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("manual-variants: _meta.json invalid, regenerating: %s", exc)
            meta = {}

    # 3) Distinctive Traits sicherstellen
    distinctive_traits = (
        meta.get("distinctive_traits")
        or job.get("distinctive_traits")
        or ""
    )
    if not distinctive_traits:
        log.info("manual-variants: generiere fehlende distinctive_traits via GPT")
        distinctive_traits = await openai_client.generate_distinctive_traits(
            pokemon_a, pokemon_b, concept, tone_hint,
        )
    meta["distinctive_traits"] = distinctive_traits

    # 4) Pokemon-DE-Namen (falls Pipeline frueh starb sind die noch nicht da)
    pokemon_a_de = meta.get("pokemon_a_de") or job.get("pokemon_a_de")
    pokemon_b_de = meta.get("pokemon_b_de") or job.get("pokemon_b_de")
    if not pokemon_a_de or not pokemon_b_de:
        try:
            names_a, names_b = await asyncio.gather(
                pokemon_refs.get_localized_names(pokemon_a),
                pokemon_refs.get_localized_names(pokemon_b),
            )
            pokemon_a_de = pokemon_a_de or names_a.get("de", pokemon_a)
            pokemon_b_de = pokemon_b_de or names_b.get("de", pokemon_b)
        except Exception as exc:  # noqa: BLE001
            log.warning("manual-variants: localized names failed (%s), using EN", exc)
            pokemon_a_de = pokemon_a_de or pokemon_a
            pokemon_b_de = pokemon_b_de or pokemon_b
    meta["pokemon_a_de"] = pokemon_a_de
    meta["pokemon_b_de"] = pokemon_b_de

    # 5) Step5 / Step6 / Showcase Image Prompt falls fehlend
    if not meta.get("step5_transformation"):
        meta["step5_transformation"] = await openai_client.generate_step5_transformation(
            pokemon_a, pokemon_b, concept, distinctive_traits,
        )
    if not meta.get("step6_showcase"):
        meta["step6_showcase"] = await openai_client.generate_step6_showcase(
            pokemon_a, pokemon_b, concept, distinctive_traits,
        )
    if not meta.get("showcase_image_prompt"):
        meta["showcase_image_prompt"] = await openai_client.generate_showcase_image_prompt(
            pokemon_a, pokemon_b, concept, distinctive_traits,
            meta["step6_showcase"],
        )

    # 6) Single-Job-Narration nur generieren wenn NICHT Batch-Member.
    #    Bei Batch-Jobs uebernimmt der Batch-Monitor die gemeinsame Narration
    #    sobald alle Mitglieder done sind.
    is_batch_member = bool(job.get("batch_id"))
    if not is_batch_member:
        if not (meta.get("narration_de") and meta.get("narration_en")):
            try:
                de, en = await openai_client.generate_narration(
                    pokemon_a, pokemon_b,
                    pokemon_a_de, pokemon_b_de,
                    distinctive_traits,
                    meta["step5_transformation"],
                    meta["step6_showcase"],
                )
                meta["narration_de"] = de
                meta["narration_en"] = en
            except Exception as exc:  # noqa: BLE001
                log.warning("manual-variants: narration failed: %s", exc)
        if not meta.get("suno_prompt"):
            try:
                meta["suno_prompt"] = await openai_client.generate_suno_prompt(
                    meta.get("narration_en", ""),
                    fusion_count=1,
                    overall_tone=distinctive_traits,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("manual-variants: suno failed: %s", exc)
        if not meta.get("yt_title"):
            try:
                yt_title, yt_desc = await openai_client.generate_yt_seo(
                    meta.get("narration_en", ""),
                    fusions=[{"pokemon_a": pokemon_a, "pokemon_b": pokemon_b}],
                    overall_tone=distinctive_traits,
                )
                meta["yt_title"] = yt_title
                meta["yt_description"] = yt_desc
            except Exception as exc:  # noqa: BLE001
                log.warning("manual-variants: yt-seo failed: %s", exc)

    # 7) ALLE existing variants im Output-Ordner sammeln (auch die die schon
    #    vorher da waren - z.B. wenn 2/3 die Pipeline geschafft haben).
    all_variant_paths: list[Path] = []
    for n in range(1, 11):
        p = out_dir / f"04_fusion_v{n}.png"
        if p.exists():
            all_variant_paths.append(p)
    if not all_variant_paths:
        raise RuntimeError("Nach Upload keine Variant-Files gefunden - irgendwas ist schiefgelaufen.")

    # 8) files-Block in meta updaten
    files_meta = dict(meta.get("files") or {})
    # step_2a / step_2b / step_3 falls vorhanden - sonst leer (Pipeline kann
    # vor Step 2 abgebrochen sein, das ist OK fuer Manual-Completion).
    for key, fname in (("step_2a", None), ("step_2b", None), ("step_3", "03_start_frame.png")):
        existing = files_meta.get(key)
        if existing:
            continue
        if fname and (out_dir / fname).exists():
            files_meta[key] = fname
    files_meta["variants"] = [p.name for p in all_variant_paths]
    files_meta["manual_variants"] = sorted(variants.keys())
    meta["files"] = files_meta
    meta["id"] = job_id
    meta["pokemon_a"] = pokemon_a
    meta["pokemon_b"] = pokemon_b
    meta["concept"] = concept
    meta["tone_hint"] = tone_hint
    meta.setdefault("created_at", job.get("created_at"))
    meta["manual_completed_at"] = _now_iso()
    meta.setdefault("finished_at", _now_iso())

    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 9) Output-MDs schreiben
    try:
        _write_video_prompts_md(
            out_dir,
            pokemon_a=pokemon_a,
            pokemon_b=pokemon_b,
            distinctive_traits=distinctive_traits,
            step5=meta["step5_transformation"],
            step6=meta["step6_showcase"],
            showcase_image_prompt=meta["showcase_image_prompt"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("manual-variants: video_prompts.md write failed: %s", exc)
    if not is_batch_member and meta.get("narration_de"):
        try:
            _write_narration_md(
                out_dir,
                meta.get("narration_de", ""),
                meta.get("narration_en", ""),
                meta.get("suno_prompt", ""),
                yt_title=meta.get("yt_title", ""),
                yt_description=meta.get("yt_description", ""),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("manual-variants: narration.md write failed: %s", exc)

    # 10) Job-State updaten
    files_map = {
        "meta_json": _relative_to_root(meta_path),
        "video_prompts_md": _relative_to_root(out_dir / "video_prompts.md"),
    }
    for key in ("step_2a", "step_2b", "step_3"):
        fname = files_meta.get(key)
        if fname and (out_dir / fname).exists():
            files_map[key] = _relative_to_root(out_dir / fname)
    if not is_batch_member and (out_dir / "narration.md").exists():
        files_map["narration_md"] = _relative_to_root(out_dir / "narration.md")

    await _update_job(
        job_id,
        status="done",
        current_step="done",
        error=None,
        variants=[_relative_to_root(p) for p in all_variant_paths],
        files=files_map,
        distinctive_traits=distinctive_traits,
        manual_completed_at=_now_iso(),
    )

    # 11) Falls Batch-Member: Batch-Monitor neu anstossen damit Compilation-
    #     Narration nach Abschluss aller Mitglieder generiert wird.
    batch_id = job.get("batch_id")
    if batch_id:
        try:
            await _update_batch(
                batch_id,
                # Status auf "running" damit der Monitor weiterlaeuft / neu startet.
                # Wenn der Batch schon done war: Narration wird neu generiert
                # nach Abschluss aller Mitglieder (siehe Batch-Monitor-Logik).
                status="running",
                error=None,
            )
            _register_task(
                f"batch:{batch_id}",
                asyncio.create_task(_run_batch_monitor(batch_id)),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("manual-variants: batch-monitor restart failed: %s", exc)

    return {
        "job_id": job_id,
        "status": "done",
        "uploaded_slots": sorted(variants.keys()),
        "total_variants": len(all_variant_paths),
        "is_batch_member": is_batch_member,
    }


async def set_showcase_pick(job_id: str, variant: int | None) -> None:
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if variant is not None and not (1 <= variant <= SHOWCASE_VARIANTS):
        raise ValueError(f"variant muss zwischen 1 und {SHOWCASE_VARIANTS} sein oder null")
    await _update_job(job_id, showcase_pick=variant)


async def toggle_checklist(job_id: str, key: str, value: bool) -> None:
    if key not in CHECKLIST_KEYS:
        raise ValueError(
            f"Ungueltiger Checklist-Key '{key}'. Erlaubt: {sorted(CHECKLIST_KEYS)}"
        )
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    checklist = dict(job.get("checklist") or {})
    checklist[key] = bool(value)
    await _update_job(job_id, checklist=checklist)


# ---------------------------------------------------------------------------
# Internals - Runner
# ---------------------------------------------------------------------------


async def _run_fusion(job_id: str) -> None:
    async with _FUSION_SEMAPHORE:
        try:
            await _update_job(job_id, status="running", current_step="starting")
            await _pipeline(job_id)
            await _update_job(job_id, status="done", current_step="done")
        except asyncio.CancelledError:
            await _update_job(
                job_id,
                status="cancelled",
                current_step="cancelled",
                error="Job wurde manuell abgebrochen.",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc()
            await _update_job(
                job_id,
                status="error",
                current_step="error",
                error=err,
                traceback=tb,
            )


async def _pipeline(job_id: str) -> None:
    job = await get_job(job_id)
    assert job is not None
    pokemon_a = job["pokemon_a"]
    pokemon_b = job["pokemon_b"]
    concept = job.get("concept") or f"A cinematic fusion of {pokemon_a} and {pokemon_b}."
    tone_hint = job.get("tone_hint")

    # 0) Signature-Background check
    if not SIGNATURE_BACKGROUND_PATH.exists():
        raise RuntimeError(
            f"Signature Background fehlt: {SIGNATURE_BACKGROUND_PATH}. "
            "Bitte Datei manuell platzieren."
        )

    # Output-Ordner
    out_dir = _make_output_dir(pokemon_a, pokemon_b)
    await _update_job(job_id, output_dir=_relative_to_root(out_dir))

    # 1) PokeAPI-Refs laden (parallel) + deutsche Namen + Hoehen fuer Size-Hint
    await _update_job(job_id, current_step="pokeapi_refs")
    ref_a_task = asyncio.create_task(pokemon_refs.fetch_official_artwork(pokemon_a))
    ref_b_task = asyncio.create_task(pokemon_refs.fetch_official_artwork(pokemon_b))
    names_a_task = asyncio.create_task(pokemon_refs.get_localized_names(pokemon_a))
    names_b_task = asyncio.create_task(pokemon_refs.get_localized_names(pokemon_b))
    height_a_task = asyncio.create_task(pokemon_refs.get_pokemon_height_m(pokemon_a))
    height_b_task = asyncio.create_task(pokemon_refs.get_pokemon_height_m(pokemon_b))
    (
        ref_a_path, ref_b_path,
        names_a, names_b,
        height_a, height_b,
    ) = await asyncio.gather(
        ref_a_task, ref_b_task,
        names_a_task, names_b_task,
        height_a_task, height_b_task,
    )
    pokemon_a_de = names_a.get("de", pokemon_a)
    pokemon_b_de = names_b.get("de", pokemon_b)

    # Size-Hint fuer Step 3 berechnen - Pokemon-Groessen koennen sehr stark
    # variieren (Rayquaza 7m vs Joltik 0.1m); ohne Hinweis rendert AI-Auto sie
    # gleich gross. Wenn ratio >= 1.5x, expliziten Hint geben.
    size_hint = "Maintain canonical body-size proportions between both Pokemon."
    if height_a and height_b and height_a > 0 and height_b > 0:
        ratio = max(height_a, height_b) / min(height_a, height_b)
        if ratio >= 1.5:
            if height_a >= height_b:
                bigger, smaller = pokemon_a, pokemon_b
                bigger_h, smaller_h = height_a, height_b
            else:
                bigger, smaller = pokemon_b, pokemon_a
                bigger_h, smaller_h = height_b, height_a
            size_hint = (
                f"Important: {bigger} is canonically much larger than {smaller} "
                f"({bigger}: ~{bigger_h:.1f}m tall, {smaller}: ~{smaller_h:.1f}m tall, "
                f"a {ratio:.1f}x size difference). This proportion MUST be visible "
                f"in the frame - {bigger} towers over {smaller}."
            )

    # 2A + 2B) Realistic Singles - parallel (Semaphore drosselt)
    await _update_job(job_id, current_step="step_2_realistic_singles")
    step2a_out = out_dir / f"02a_realistic_{_folder_slug(pokemon_a)}.png"
    step2b_out = out_dir / f"02b_realistic_{_folder_slug(pokemon_b)}.png"

    step2a = asyncio.create_task(
        _step2_realistic_cached(pokemon_a, ref_a_path, step2a_out)
    )
    step2b = asyncio.create_task(
        _step2_realistic_cached(pokemon_b, ref_b_path, step2b_out)
    )
    (_, cache_a), (_, cache_b) = await asyncio.gather(step2a, step2b)
    if cache_a or cache_b:
        await _update_job(
            job_id,
            cache_hits=[
                p for p, hit in [(pokemon_a, cache_a), (pokemon_b, cache_b)] if hit
            ],
        )

    # 3) Start Frame - referenzen: signature background (=ref1), 2A, 2B
    await _update_job(job_id, current_step="step_3_start_frame")
    step3_out = out_dir / "03_start_frame.png"
    step3_prompt = (
        prompts.STEP3_START_FRAME
        .replace("{POKEMON_A}", pokemon_a)
        .replace("{POKEMON_B}", pokemon_b)
        .replace("{SIZE_HINT}", size_hint)
        .strip()
    )
    await aiauto_client.generate_image(
        step3_prompt,
        step3_out,
        reference_images=[SIGNATURE_BACKGROUND_PATH, step2a_out, step2b_out],
    )

    # GPT) Distinctive Traits
    await _update_job(job_id, current_step="gpt_distinctive_traits")
    distinctive_traits = await openai_client.generate_distinctive_traits(
        pokemon_a, pokemon_b, concept, tone_hint
    )

    # 4) Fusion-Design-Varianten - parallel (Semaphore drosselt auf 4)
    await _update_job(job_id, current_step="step_4_fusion_variants")
    step4_prompt = (
        prompts.STEP4_FUSION_DESIGN_TEMPLATES.get(
            settings.step4_design_mode,
            prompts.STEP4_FUSION_DESIGN_BLEND,
        )
        .replace("{POKEMON_A}", pokemon_a)
        .replace("{POKEMON_B}", pokemon_b)
        .replace("{DISTINCTIVE_TRAITS}", distinctive_traits)
    )
    variant_tasks = []
    variant_paths: list[Path] = []
    for i in range(1, STEP4_VARIANTS + 1):
        vpath = out_dir / f"04_fusion_v{i}.png"
        variant_paths.append(vpath)
        variant_tasks.append(
            aiauto_client.generate_image(
                step4_prompt,
                vpath,
                reference_images=[SIGNATURE_BACKGROUND_PATH, step2a_out, step2b_out],
            )
        )
    # return_exceptions=True: partial success akzeptieren.
    results = await asyncio.gather(*variant_tasks, return_exceptions=True)
    success_paths: list[Path] = []
    step4_errors: list[str] = []
    for i, res in enumerate(results):
        if isinstance(res, BaseException):
            step4_errors.append(f"v{i+1}: {type(res).__name__}: {res}")
        else:
            success_paths.append(variant_paths[i])
    if not success_paths:
        raise RuntimeError("Alle Varianten fehlgeschlagen: " + " | ".join(step4_errors))
    variant_paths = success_paths

    # GPT) Step 5, Step 6, Narration - parallel
    await _update_job(job_id, current_step="gpt_video_prompts")
    step5_task = asyncio.create_task(
        openai_client.generate_step5_transformation(
            pokemon_a, pokemon_b, concept, distinctive_traits
        )
    )
    step6_task = asyncio.create_task(
        openai_client.generate_step6_showcase(
            pokemon_a, pokemon_b, concept, distinctive_traits
        )
    )
    step5_text, step6_text = await asyncio.gather(step5_task, step6_task)

    # Showcase-Image-Prompt (statisches Power-Pose Frame fuer Kling Elements
    # @image2 / Flow Blueprint). Kondensiert step6 zu einem Frame.
    await _update_job(job_id, current_step="gpt_showcase_image_prompt")
    showcase_image_prompt = await openai_client.generate_showcase_image_prompt(
        pokemon_a, pokemon_b, concept, distinctive_traits, step6_text,
    )

    # Einzelne Narration ueberspringen, wenn Teil eines Batches -
    # der Batch-Monitor generiert spaeter die gemeinsame Narration + Suno + YT SEO.
    is_batch_member = bool(job.get("batch_id"))
    suno_prompt = ""
    yt_title = ""
    yt_description = ""
    if is_batch_member:
        narration_de = ""
        narration_en = ""
    else:
        await _update_job(job_id, current_step="gpt_narration")
        narration_de, narration_en = await openai_client.generate_narration(
            pokemon_a, pokemon_b,
            pokemon_a_de, pokemon_b_de,
            distinctive_traits, step5_text, step6_text,
        )
        await _update_job(job_id, current_step="gpt_suno_prompt")
        suno_prompt = await openai_client.generate_suno_prompt(
            narration_en,
            fusion_count=1,
            overall_tone=distinctive_traits,
        )
        await _update_job(job_id, current_step="gpt_yt_seo")
        yt_title, yt_description = await openai_client.generate_yt_seo(
            narration_en,
            fusions=[{"pokemon_a": pokemon_a, "pokemon_b": pokemon_b}],
            overall_tone=distinctive_traits,
        )

    # Dateien schreiben
    await _update_job(job_id, current_step="writing_outputs")
    meta = {
        "id": job_id,
        "pokemon_a": pokemon_a,
        "pokemon_b": pokemon_b,
        "pokemon_a_de": pokemon_a_de,
        "pokemon_b_de": pokemon_b_de,
        "concept": concept,
        "tone_hint": tone_hint,
        "distinctive_traits": distinctive_traits,
        "step5_transformation": step5_text,
        "step6_showcase": step6_text,
        "showcase_image_prompt": showcase_image_prompt,
        "narration_de": narration_de,
        "narration_en": narration_en,
        "suno_prompt": suno_prompt,
        "yt_title": yt_title,
        "yt_description": yt_description,
        "files": {
            "step_2a": step2a_out.name,
            "step_2b": step2b_out.name,
            "step_3": step3_out.name,
            "variants": [p.name for p in variant_paths],
        },
        "created_at": job.get("created_at"),
        "finished_at": _now_iso(),
    }
    (out_dir / "_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _write_video_prompts_md(
        out_dir,
        pokemon_a=pokemon_a,
        pokemon_b=pokemon_b,
        distinctive_traits=distinctive_traits,
        step5=step5_text,
        step6=step6_text,
        showcase_image_prompt=showcase_image_prompt,
    )
    if not is_batch_member:
        _write_narration_md(
            out_dir, narration_de, narration_en, suno_prompt,
            yt_title=yt_title, yt_description=yt_description,
        )

    files_map = {
        "step_2a": _relative_to_root(step2a_out),
        "step_2b": _relative_to_root(step2b_out),
        "step_3": _relative_to_root(step3_out),
        "video_prompts_md": _relative_to_root(out_dir / "video_prompts.md"),
        "meta_json": _relative_to_root(out_dir / "_meta.json"),
    }
    if not is_batch_member:
        files_map["narration_md"] = _relative_to_root(out_dir / "narration.md")

    await _update_job(
        job_id,
        variants=[_relative_to_root(p) for p in variant_paths],
        files=files_map,
        distinctive_traits=distinctive_traits,
    )


async def _run_regenerate(job_id: str, variant_index: int) -> None:
    async with _FUSION_SEMAPHORE:
        try:
            await _update_job(
                job_id,
                status="running",
                current_step=f"regenerate_v{variant_index}",
                error=None,
            )
            job = await get_job(job_id)
            assert job is not None
            out_dir = PROJECT_ROOT / job["output_dir"]
            meta_path = out_dir / "_meta.json"
            if not meta_path.exists():
                raise RuntimeError("_meta.json fehlt, Regenerate nicht moeglich.")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pokemon_a = meta["pokemon_a"]
            pokemon_b = meta["pokemon_b"]
            distinctive_traits = meta["distinctive_traits"]

            step4_prompt = (
                prompts.STEP4_FUSION_DESIGN_TEMPLATES.get(
                    settings.step4_design_mode,
                    prompts.STEP4_FUSION_DESIGN_BLEND,
                )
                .replace("{POKEMON_A}", pokemon_a)
                .replace("{POKEMON_B}", pokemon_b)
                .replace("{DISTINCTIVE_TRAITS}", distinctive_traits)
            )
            vpath = out_dir / f"04_fusion_v{variant_index}.png"
            step2a_out = out_dir / meta["files"]["step_2a"]
            step2b_out = out_dir / meta["files"]["step_2b"]

            await aiauto_client.generate_image(
                step4_prompt,
                vpath,
                reference_images=[SIGNATURE_BACKGROUND_PATH, step2a_out, step2b_out],
            )
            await _update_job(job_id, status="done", current_step="done")
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            await _update_job(job_id, status="error", current_step="error", error=err)


# ---------------------------------------------------------------------------
# Markdown-Outputs
# ---------------------------------------------------------------------------


def _write_video_prompts_md(
    out_dir: Path,
    *,
    pokemon_a: str,
    pokemon_b: str,
    distinctive_traits: str,
    step5: str,
    step6: str,
    showcase_image_prompt: str = "",
) -> None:
    # Step 6B Kling Elements - prepend + append magic instructions
    step6b_wrapped = (
        f"{prompts.STEP6B_PREPEND}\n\n"
        f"{step6}\n\n"
        f"{prompts.STEP6B_APPEND}"
    )

    md = f"""# Video Prompts - {pokemon_a} x {pokemon_b}

> Copy-paste-ready prompts fuer Kling (Step 5 Transformation) und
> Higgsfield/Seedance + Kling Elements (Step 6 Showcase).

---

## Distinctive Traits (used in Step 4)

{distinctive_traits}

---

## Step 5 - Transformation (Kling 2.5 / Kling 3.0 Omni)

Use Kling's First-Last-Frame mode (best results) and paste the prompt
as a single paragraph. Let the prompt steer the transformation between
the two frames.

- Start Frame: `03_start_frame.png`  (the two Pokemon side by side)
- End Frame:   `04_fusion_vX.png`    (your chosen favorite - one of v1..v5)

If your Kling tier only offers a single start frame (no end-frame slot),
upload `03_start_frame.png` and rely on the prompt to describe the
final creature - the End Frame enforces the favorite design much more
precisely though.

```
{step5}
```

---

## Step 6A - Showcase (Seedance 2 via Higgsfield) - PRIMARY

Upload your chosen Step-4 variant (one of `04_fusion_v1.png` ... `v5.png`)
as the reference image. Seedance will check if the design is eligible;
if yes, paste the prompt, set 16:9, and render. You get a 10s clip with
5 cuts in one go.

```
{step6}
```

---

## Step 7 - Showcase Image Prompt (static blueprint frame)

If Seedance is unavailable or rejects the design, you need a static
'shot director' image for Kling Elements. The Dashboard's
'Generate Showcase' button uses this prompt automatically (4 variants
in 16:9). You can also paste it manually into Flow or any other image
model that takes the favorite fusion variant as reference.

```
{showcase_image_prompt}
```

---

## Step 6B - Showcase Fallback (Flow -> Kling Elements)

Only needed if Seedance rejects the design. Two-stage workflow:

1. Get a blueprint image - either via the Dashboard 'Generate Showcase'
   button (uses Step-7 prompt above), or in **Flow** by pasting the
   Step-6 showcase prompt with your favorite fusion variant as reference,
   16:9. Save as `blueprint.png`.

2. In **Kling 3.0 Omni**, switch to **ELEMENTS mode (NOT Images)** and
   upload three elements:
   - `@image1` = `04_fusion_vX.png`       (your favorite variant - locks DESIGN)
   - `@image2` = `blueprint.png`          (shot director from Flow / Step 7)
   - `@image3` = `03_start_frame.png`     (background consistency)

   Paste the wrapped prompt below (already has the `@image1..3` magic
   instructions prepended/appended):

```
{step6b_wrapped}
```

---

## Step 9 - Editing Notes

- Time-ramps: slow down the TRIGGER MOMENT (bite/grab), snap back to speed
  during the ESCALATING TRANSFORMATION, slow again for the FINAL ROAR.
- Background track: cinematic/epic orchestral with a sub-bass drop on the
  trigger and a release on the final roar.
- SFX: low rumble during transformation, layered glass-crack / bone-crunch
  at body-part mutation, whoosh on camera push-ins, deep impact on final.
- Cut Step 5 first (10s), then Step 6 (10s). Total ~20s Reel.
"""
    (out_dir / "video_prompts.md").write_text(md, encoding="utf-8")


def _write_narration_md(
    out_dir: Path,
    narration_de: str,
    narration_en: str,
    suno_prompt: str = "",
    yt_title: str = "",
    yt_description: str = "",
) -> None:
    md = f"""# Narration - DE / EN

> Voice-over-Texte fuer den deutschen und englischen Account. Beide Versionen
> sind auf die Visuals (Step 5 Transformation + Step 6 Showcase) abgestimmt
> und beginnen mit dem festgelegten Opener.

---

## Deutsch

{narration_de}

---

## English

{narration_en}
"""
    if suno_prompt:
        md += (
            "\n---\n\n## Suno Background Music Prompt\n\n"
            f"{suno_prompt}\n"
        )
    if yt_title or yt_description:
        md += "\n---\n\n## YouTube Shorts SEO\n\n"
        if yt_title:
            md += f"**Title:** {yt_title}\n\n"
        if yt_description:
            md += f"**Description:**\n\n{yt_description}\n"
    (out_dir / "narration.md").write_text(md, encoding="utf-8")
