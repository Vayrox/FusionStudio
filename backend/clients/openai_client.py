"""
GPT-4o Wrapper fuer alle Text-Generations der Pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

import httpx
from openai import APIError, APITimeoutError, APIConnectionError, AsyncOpenAI, RateLimitError

from backend.config import settings
from backend import prompts

log = logging.getLogger("fusion-auto.openai")

# Pro Chat-Call: Hard-Timeout + Retries mit Exponential Backoff.
_OPENAI_TIMEOUT_S = 120.0
_OPENAI_RETRIES = 3


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
    last_exc: Exception | None = None
    for attempt in range(1, _OPENAI_RETRIES + 1):
        try:
            kwargs: dict[str, Any] = {
                "model": settings.openai_model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "timeout": _OPENAI_TIMEOUT_S,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            log.warning(
                "OpenAI chat.completions attempt %d/%d (model=%s, max_tokens=%s)",
                attempt, _OPENAI_RETRIES, settings.openai_model, max_tokens,
            )
            resp = await client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            log.warning(
                "OpenAI chat.completions attempt %d/%d -> %d chars",
                attempt, _OPENAI_RETRIES, len(text),
            )
            return text
        except (APITimeoutError, APIConnectionError, httpx.TimeoutException,
                httpx.NetworkError) as exc:
            last_exc = exc
            log.warning(
                "OpenAI network error on attempt %d/%d: %s",
                attempt, _OPENAI_RETRIES, exc,
            )
        except RateLimitError as exc:
            last_exc = exc
            log.warning(
                "OpenAI rate limit on attempt %d/%d: %s",
                attempt, _OPENAI_RETRIES, exc,
            )
        except APIError as exc:
            last_exc = exc
            log.warning(
                "OpenAI API error on attempt %d/%d: %s",
                attempt, _OPENAI_RETRIES, exc,
            )
        if attempt < _OPENAI_RETRIES:
            await asyncio.sleep(2 ** attempt)
    assert last_exc is not None
    raise RuntimeError(
        f"OpenAI chat.completions fehlgeschlagen nach {_OPENAI_RETRIES} Versuchen: {last_exc}"
    ) from last_exc


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
    pokemon_a_de: str,
    pokemon_b_de: str,
    distinctive_traits: str,
    step5: str,
    step6: str,
) -> tuple[str, str]:
    """Gibt (narration_de, narration_en) zurueck.

    Die DE-Namen werden in der deutschen Narration verwendet, EN-Namen
    in der englischen. FUSION_NAME ist identisch in beiden Sprachen.
    """
    user = prompts.GPT_NARRATION_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        POKEMON_A_DE=pokemon_a_de,
        POKEMON_B_DE=pokemon_b_de,
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


async def generate_batch_narration(fusions: list[dict[str, str]]) -> tuple[str, str]:
    """Generiert EINE durchgehende DE+EN Narration fuer eine Liste von Fusionen.

    Jede Fusion im Input dict muss haben:
      pokemon_a, pokemon_b, distinctive_traits, step5_transformation, step6_showcase
    """
    if not fusions:
        raise ValueError("Keine Fusionen fuer Batch-Narration uebergeben.")
    parts: list[str] = []
    for i, f in enumerate(fusions, start=1):
        en_pair = f"{f.get('pokemon_a', '?')} + {f.get('pokemon_b', '?')}"
        de_pair = f"{f.get('pokemon_a_de', f.get('pokemon_a', '?'))} + {f.get('pokemon_b_de', f.get('pokemon_b', '?'))}"
        parts.append(
            f"### Fusion {i}\n"
            f"English names: {en_pair}\n"
            f"German names: {de_pair}\n"
            f"Distinctive Traits: {f.get('distinctive_traits', '')}\n\n"
            f"Transformation context:\n{f.get('step5_transformation', '')}\n\n"
            f"Showcase context:\n{f.get('step6_showcase', '')}\n"
        )
    fusions_block = "\n---\n".join(parts)

    user = prompts.GPT_BATCH_NARRATION_USER_TEMPLATE.format(
        FUSION_COUNT=len(fusions),
        FUSIONS_BLOCK=fusions_block,
        OPENER_DE=prompts.NARRATION_OPENER_DE,
        OPENER_EN=prompts.NARRATION_OPENER_EN,
    )
    raw = await _chat(
        prompts.GPT_BATCH_NARRATION_SYSTEM,
        user,
        temperature=0.85,
        max_tokens=4000,
    )
    match = _NARRATION_SPLIT_RE.search(raw)
    if not match:
        raise ValueError(f"Konnte DE/EN-Batch-Narration nicht parsen: {raw!r}")
    de = match.group("de").strip()
    en = match.group("en").strip()
    if not de.lower().startswith(prompts.NARRATION_OPENER_DE.lower()[:20]):
        de = prompts.NARRATION_OPENER_DE + " " + de
    if not en.lower().startswith(prompts.NARRATION_OPENER_EN.lower()[:20]):
        en = prompts.NARRATION_OPENER_EN + " " + en
    return de, en
