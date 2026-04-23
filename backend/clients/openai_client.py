"""
GPT-4o Wrapper fuer alle Text-Generations der Pipeline.
"""
from __future__ import annotations

import json
import random
import re
from typing import Any

from openai import AsyncOpenAI

from backend.config import settings
from backend import prompts


def _client() -> AsyncOpenAI:
    key = settings.openai_api_key
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY ist nicht gesetzt. Im Dashboard unter Settings eintragen."
        )
    return AsyncOpenAI(api_key=key)


async def _chat(
    system: str,
    user: str,
    temperature: float = 0.9,
    max_tokens: int | None = None,
) -> str:
    client = _client()
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    resp = await client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Ideas Generator
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    return _JSON_FENCE_RE.sub("", text).strip()


async def generate_fusion_ideas(hint: str) -> list[dict[str, str]]:
    """Gibt eine Liste von 6 Fusion-Ideen zurueck: [{pokemon_a, pokemon_b, concept}, ...]."""
    seed = str(random.randint(100000, 999999))
    user = prompts.GPT_IDEAS_GENERATOR_USER_TEMPLATE.format(HINT=hint, SEED=seed)
    raw = await _chat(prompts.GPT_IDEAS_GENERATOR_SYSTEM, user, temperature=1.0)
    raw = _strip_code_fence(raw)

    # Manchmal gibt GPT trotzdem einen JSON-Text mit umliegendem Prosa-Zeug aus.
    # Wir extrahieren den ersten JSON-Array-Block defensiv.
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Konnte JSON-Array aus GPT-Antwort nicht extrahieren: {raw!r}")
    ideas = json.loads(match.group(0))

    if not isinstance(ideas, list):
        raise ValueError("GPT-Antwort ist kein JSON-Array.")

    cleaned: list[dict[str, str]] = []
    for i, item in enumerate(ideas):
        if not isinstance(item, dict):
            continue
        a = str(item.get("pokemon_a", "")).strip()
        b = str(item.get("pokemon_b", "")).strip()
        c = str(item.get("concept", "")).strip()
        if not (a and b and c):
            continue
        cleaned.append({"pokemon_a": a, "pokemon_b": b, "concept": c})
    if len(cleaned) < 1:
        raise ValueError("GPT lieferte keine valide Fusion-Idee.")
    return cleaned[:6]


# ---------------------------------------------------------------------------
# Distinctive Traits
# ---------------------------------------------------------------------------


async def generate_distinctive_traits(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    tone_hint: str | None = None,
) -> str:
    user = prompts.GPT_DISTINCTIVE_TRAITS_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        TONE_HINT=tone_hint or "(none - choose freely)",
    )
    return await _chat(
        prompts.GPT_DISTINCTIVE_TRAITS_SYSTEM,
        user,
        temperature=0.95,
        max_tokens=400,
    )


# ---------------------------------------------------------------------------
# Step 5 Transformation
# ---------------------------------------------------------------------------


async def generate_step5_transformation(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    distinctive_traits: str,
) -> str:
    user = prompts.GPT_STEP5_TRANSFORMATION_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        DISTINCTIVE_TRAITS=distinctive_traits,
    )
    return await _chat(
        prompts.GPT_STEP5_TRANSFORMATION_SYSTEM,
        user,
        temperature=0.9,
        max_tokens=1800,
    )


# ---------------------------------------------------------------------------
# Step 6 Showcase
# ---------------------------------------------------------------------------


async def generate_step6_showcase(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    distinctive_traits: str,
) -> str:
    user = prompts.GPT_STEP6_SHOWCASE_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        DISTINCTIVE_TRAITS=distinctive_traits,
    )
    return await _chat(
        prompts.GPT_STEP6_SHOWCASE_SYSTEM,
        user,
        temperature=0.9,
        max_tokens=1200,
    )


# ---------------------------------------------------------------------------
# Narration (DE + EN)
# ---------------------------------------------------------------------------

_NARRATION_SPLIT_RE = re.compile(
    r"---\s*DE\s*---\s*(?P<de>.*?)\s*---\s*EN\s*---\s*(?P<en>.*?)\s*---\s*END\s*---",
    re.DOTALL | re.IGNORECASE,
)


async def generate_narration(
    pokemon_a: str,
    pokemon_b: str,
    distinctive_traits: str,
    step5: str,
    step6: str,
) -> tuple[str, str]:
    """Gibt (narration_de, narration_en) zurueck."""
    user = prompts.GPT_NARRATION_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        DISTINCTIVE_TRAITS=distinctive_traits,
        STEP5=step5,
        STEP6=step6,
        OPENER_DE=prompts.NARRATION_OPENER_DE,
        OPENER_EN=prompts.NARRATION_OPENER_EN,
    )
    raw = await _chat(
        prompts.GPT_NARRATION_SYSTEM,
        user,
        temperature=0.85,
        max_tokens=1400,
    )
    match = _NARRATION_SPLIT_RE.search(raw)
    if not match:
        raise ValueError(f"Konnte DE/EN-Narration nicht parsen: {raw!r}")
    de = match.group("de").strip()
    en = match.group("en").strip()

    # Opener hart enforcen, falls GPT sie doch verwaesserst.
    if not de.lower().startswith(prompts.NARRATION_OPENER_DE.lower()[:20]):
        de = prompts.NARRATION_OPENER_DE + " " + de
    if not en.lower().startswith(prompts.NARRATION_OPENER_EN.lower()[:20]):
        en = prompts.NARRATION_OPENER_EN + " " + en
    return de, en
