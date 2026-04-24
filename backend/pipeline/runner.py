"""
Pipeline-Orchestrator. Fuehrt fuer jede Fusion die Steps 2A, 2B, 3, Traits,
4 (x5 Varianten), 5, 6, Narration aus und schreibt Output-Assets.

State-Persistenz: .state/jobs.json ueberlebt Browser-Refresh und Server-Neustart.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend import prompts
from backend.clients import aiauto_client, openai_client, pokemon_refs
from backend.config import (
    MAX_PARALLEL_FUSIONS,
    OUTPUT_DIR,
    PROJECT_ROOT,
    REALISTIC_CACHE_DIR,
    SIGNATURE_BACKGROUND_PATH,
    STATE_FILE,
    STEP4_VARIANTS,
)

# ---------------------------------------------------------------------------
# Job-Semaphore + State
# ---------------------------------------------------------------------------

_FUSION_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_FUSIONS)
_STATE_LOCK = asyncio.Lock()
_STATE_CACHE: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


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
        return dict(job)


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
) -> str:
    """Queued eine neue Fusion. Gibt job_id zurueck. Pipeline laeuft im Hintergrund."""
    job_id = uuid.uuid4().hex[:12]
    await _update_job(
        job_id,
        id=job_id,
        pokemon_a=pokemon_a,
        pokemon_b=pokemon_b,
        concept=concept,
        tone_hint=tone_hint,
        status="queued",
        current_step="queued",
        error=None,
        output_dir=None,
        variants=[],
        created_at=_now_iso(),
    )
    asyncio.create_task(_run_fusion(job_id))
    return job_id


async def regenerate_variant(job_id: str, variant_index: int) -> None:
    """Regeneriert EINE Step-4-Variante. Nutzt gleiches Distinctive-Traits."""
    job = await get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} nicht gefunden")
    if job.get("status") != "done":
        raise ValueError("Regenerate nur erlaubt, wenn Job bereits 'done' ist.")
    if not (1 <= variant_index <= STEP4_VARIANTS):
        raise ValueError(f"variant_index muss zwischen 1 und {STEP4_VARIANTS} liegen")

    asyncio.create_task(_run_regenerate(job_id, variant_index))


# ---------------------------------------------------------------------------
# Internals - Runner
# ---------------------------------------------------------------------------


async def _run_fusion(job_id: str) -> None:
    async with _FUSION_SEMAPHORE:
        try:
            await _update_job(job_id, status="running", current_step="starting")
            await _pipeline(job_id)
            await _update_job(job_id, status="done", current_step="done")
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

    # 1) PokeAPI-Refs laden (parallel)
    await _update_job(job_id, current_step="pokeapi_refs")
    ref_a_task = asyncio.create_task(pokemon_refs.fetch_official_artwork(pokemon_a))
    ref_b_task = asyncio.create_task(pokemon_refs.fetch_official_artwork(pokemon_b))
    ref_a_path, ref_b_path = await asyncio.gather(ref_a_task, ref_b_task)

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
    await aiauto_client.generate_image(
        prompts.STEP3_START_FRAME,
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
        prompts.STEP4_FUSION_DESIGN
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
    await asyncio.gather(*variant_tasks)

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

    await _update_job(job_id, current_step="gpt_narration")
    narration_de, narration_en = await openai_client.generate_narration(
        pokemon_a, pokemon_b, distinctive_traits, step5_text, step6_text
    )

    # Dateien schreiben
    await _update_job(job_id, current_step="writing_outputs")
    meta = {
        "id": job_id,
        "pokemon_a": pokemon_a,
        "pokemon_b": pokemon_b,
        "concept": concept,
        "tone_hint": tone_hint,
        "distinctive_traits": distinctive_traits,
        "step5_transformation": step5_text,
        "step6_showcase": step6_text,
        "narration_de": narration_de,
        "narration_en": narration_en,
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
    )
    _write_narration_md(out_dir, narration_de, narration_en)

    await _update_job(
        job_id,
        variants=[_relative_to_root(p) for p in variant_paths],
        files={
            "step_2a": _relative_to_root(step2a_out),
            "step_2b": _relative_to_root(step2b_out),
            "step_3": _relative_to_root(step3_out),
            "video_prompts_md": _relative_to_root(out_dir / "video_prompts.md"),
            "narration_md": _relative_to_root(out_dir / "narration.md"),
            "meta_json": _relative_to_root(out_dir / "_meta.json"),
        },
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
                prompts.STEP4_FUSION_DESIGN
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

Paste this as a single paragraph into Kling. Start frame: `03_start_frame.png`.

```
{step5}
```

---

## Step 6A - Showcase (Seedance via Higgsfield)

Paste this into Higgsfield / Seedance. Use one of the Step-4 variants as a
reference image (pick the best one).

```
{step6}
```

---

## Step 6B - Showcase (Kling Elements)

Upload these three images before running:
- `@image1` = chosen Step-4 fusion variant (locks the DESIGN)
- `@image2` = shot director reference (e.g. a cinematic still that matches
  the vibe; optional - if you don't have one, reuse `@image1`)
- `@image3` = `03_start_frame.png` (START FRAME)

Prompt (already wrapped with prepend + append magic instructions):

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


def _write_narration_md(out_dir: Path, narration_de: str, narration_en: str) -> None:
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
    (out_dir / "narration.md").write_text(md, encoding="utf-8")
