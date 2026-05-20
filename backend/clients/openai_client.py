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


def _vision_client_and_model() -> tuple[AsyncOpenAI, str]:
    """Liefert (client, model_name) fuer Vision-Tasks basierend auf
    settings.vision_provider. Gemini wird via OpenAI-kompatiblen Endpoint
    angesprochen, also funktioniert die gleiche chat.completions API."""
    provider = settings.vision_provider
    if provider == "gemini":
        key = settings.google_api_key
        if not key:
            raise RuntimeError(
                "Vision-Provider auf Gemini gesetzt, aber GOOGLE_API_KEY fehlt. "
                "Im Dashboard unter Settings eintragen."
            )
        return (
            AsyncOpenAI(
                api_key=key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            settings.gemini_vision_model or "gemini-2.5-flash",
        )
    # default: OpenAI
    return _client(), settings.openai_model


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
# Seedance prompt safety: hard-cap at 2000 chars (Seedance API limit).
# GPT meistens erfuellt das via System-Prompt-Anweisung, aber falls es doch
# rueberlaeuft, truncaten wir am letzten Satz-Ende statt mitten im Wort.
# ---------------------------------------------------------------------------

# 1900 statt 2000: gibt 100 Zeichen Buffer unter der echten Seedance-Grenze,
# damit Unicode / Whitespace / Edge-Cases nicht zur API-Rejection fuehren.
SEEDANCE_PROMPT_MAX_CHARS = 1900


def _enforce_seedance_char_limit(text: str, label: str) -> str:
    text = text.strip()
    if len(text) <= SEEDANCE_PROMPT_MAX_CHARS:
        return text
    # Suche letzten Satz-Boundary (".", "!", "?") vor dem Limit.
    cutoff = -1
    for sep in (". ", "! ", "? ", ".", "!", "?"):
        idx = text.rfind(sep, 0, SEEDANCE_PROMPT_MAX_CHARS)
        if idx > cutoff:
            cutoff = idx + len(sep.rstrip())
    if cutoff < SEEDANCE_PROMPT_MAX_CHARS // 2:
        # Kein guter Satz-Boundary gefunden - faelle auf letzte Wort-Grenze.
        cutoff = text.rfind(" ", 0, SEEDANCE_PROMPT_MAX_CHARS)
        if cutoff < 0:
            cutoff = SEEDANCE_PROMPT_MAX_CHARS
    truncated = text[:cutoff].rstrip()
    log.warning(
        "Seedance prompt %s was %d chars (over %d) - truncated to %d chars at sentence boundary",
        label, len(text), SEEDANCE_PROMPT_MAX_CHARS, len(truncated),
    )
    return truncated


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
    raw = await _chat(
        prompts.GPT_STEP5_TRANSFORMATION_SYSTEM,
        user,
        temperature=0.9,
        max_tokens=600,
    )
    return _enforce_seedance_char_limit(raw, "step5_transformation")


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
    raw = await _chat(
        prompts.GPT_STEP6_SHOWCASE_SYSTEM,
        user,
        temperature=0.9,
        max_tokens=600,
    )
    return _enforce_seedance_char_limit(raw, "step6_showcase")


async def generate_showcase_image_prompt(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    distinctive_traits: str,
    step6_video_prompt: str,
) -> str:
    """Generiert einen Static-Image-Prompt fuer ein 16:9 Showcase-Bild
    (Kling Elements @image2 / Flow Blueprint). Kondensiert den 5-Cut-
    Video-Prompt auf den entscheidenden Power-Moment in einem Frame.
    """
    user = prompts.GPT_SHOWCASE_IMAGE_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        DISTINCTIVE_TRAITS=distinctive_traits,
        STEP6_VIDEO_PROMPT=step6_video_prompt,
    )
    return await _chat(
        prompts.GPT_SHOWCASE_IMAGE_SYSTEM,
        user,
        temperature=0.85,
        max_tokens=900,
    )


async def generate_action_scene_prompt(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    distinctive_traits: str,
    step6_video_prompt: str,
) -> str:
    """Generiert einen Action-Scene Seedance-Prompt fokussiert auf reine
    Bewegung durch den Raum (ultra-high-speed tracking, motion blur).
    Komplementaer zum Standard-5-Cut-Showcase. Pokemon-Namen werden im
    Output NICHT verwendet - nur Silhouette + Traits."""
    user = prompts.GPT_ACTION_SCENE_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        DISTINCTIVE_TRAITS=distinctive_traits,
        STEP6_VIDEO_PROMPT=step6_video_prompt,
    )
    raw = await _chat(
        prompts.GPT_ACTION_SCENE_SYSTEM,
        user,
        temperature=0.9,
        max_tokens=600,
    )
    return _enforce_seedance_char_limit(raw, "action_scene")


async def generate_funny_scene_prompt(
    pokemon_a: str,
    pokemon_b: str,
    concept: str,
    distinctive_traits: str,
    step6_video_prompt: str,
    gag_hint: str = "",
) -> str:
    """Generiert einen 5-Sekunden Funny-Scene Seedance-Prompt - ein One-Shot
    Comedy-Gag basierend auf dem Element / Anatomie der Fusion (Vulplaxo
    Fire-Fart als Tonal Reference). Pokemon-Namen werden im Output NICHT
    verwendet. gag_hint optional - wenn leer waehlt GPT selbst den Gag
    aus den Traits."""
    user = prompts.GPT_FUNNY_SCENE_USER_TEMPLATE.format(
        POKEMON_A=pokemon_a,
        POKEMON_B=pokemon_b,
        CONCEPT=concept,
        DISTINCTIVE_TRAITS=distinctive_traits,
        STEP6_VIDEO_PROMPT=step6_video_prompt,
        GAG_HINT=gag_hint.strip() or "(none - pick the gag yourself)",
    )
    raw = await _chat(
        prompts.GPT_FUNNY_SCENE_SYSTEM,
        user,
        temperature=0.95,
        max_tokens=600,
    )
    return _enforce_seedance_char_limit(raw, "funny_scene")


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
    words_per_fusion: int | None = None,
) -> tuple[str, str]:
    """Gibt (narration_de, narration_en) zurueck.

    Die DE-Namen werden in der deutschen Narration verwendet, EN-Namen
    in der englischen. FUSION_NAME ist identisch in beiden Sprachen.

    words_per_fusion ueberschreibt den Default-Word-Budget im System-Prompt
    (sonst aus settings.narration_words_per_fusion).
    """
    if words_per_fusion is None:
        words_per_fusion = settings.narration_words_per_fusion
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
        WORDS_PER_FUSION=int(words_per_fusion),
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


async def generate_batch_narration(
    fusions: list[dict[str, str]],
    words_per_fusion: int | None = None,
) -> tuple[str, str]:
    """Generiert EINE durchgehende DE+EN Narration fuer eine Liste von Fusionen.

    Jede Fusion im Input dict muss haben:
      pokemon_a, pokemon_b, distinctive_traits, step5_transformation, step6_showcase

    words_per_fusion ueberschreibt den Default-Word-Budget im System-Prompt
    (sonst aus settings.narration_words_per_fusion).
    """
    if not fusions:
        raise ValueError("Keine Fusionen fuer Batch-Narration uebergeben.")
    if words_per_fusion is None:
        words_per_fusion = settings.narration_words_per_fusion
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
        WORDS_PER_FUSION=int(words_per_fusion),
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


async def generate_suno_prompt(
    narration: str,
    fusion_count: int = 1,
    overall_tone: str = "cinematic epic, hauntingly majestic",
) -> str:
    """Generiert einen Suno-Music-Prompt passend zur Narration.

    Nimmt die englische Narration als Pacing/Mood-Referenz und den
    overall_tone als zusaetzlichen Mood-Hint. Einpacken der Distinctive-
    Traits in overall_tone ist sinnvoll wenn verfuegbar.
    """
    user = prompts.GPT_SUNO_PROMPT_USER_TEMPLATE.format(
        FUSION_COUNT=fusion_count,
        OVERALL_TONE=overall_tone,
        NARRATION=narration,
    )
    return await _chat(
        prompts.GPT_SUNO_PROMPT_SYSTEM,
        user,
        temperature=0.85,
        max_tokens=400,
    )


_YT_SEO_RE = re.compile(
    r"---\s*TITLE\s*---\s*(?P<title>.*?)\s*---\s*DESCRIPTION\s*---\s*(?P<desc>.*?)\s*---\s*END\s*---",
    re.DOTALL | re.IGNORECASE,
)


async def generate_yt_seo(
    narration: str,
    fusions: list[dict[str, str]],
    overall_tone: str = "cinematic epic, hauntingly majestic",
) -> tuple[str, str]:
    """Gibt (title, description) fuer YouTube Shorts zurueck.

    Title: 40-70 chars, mit Hook + Emoji.
    Description: erste Zeile als Feed-Hook, Fusion-Liste, CTA, 12-18 Hashtags.
    """
    fusion_count = len(fusions)
    mode = "compilation_batch" if fusion_count > 1 else "single_fusion"
    fusions_list = "\n".join(
        f"- {f.get('pokemon_a', '?')} x {f.get('pokemon_b', '?')}"
        for f in fusions
    ) or "- (none)"

    user = prompts.GPT_YT_SEO_USER_TEMPLATE.format(
        MODE=mode,
        FUSION_COUNT=fusion_count,
        FUSIONS_LIST=fusions_list,
        OVERALL_TONE=overall_tone,
        NARRATION=narration,
    )
    raw = await _chat(
        prompts.GPT_YT_SEO_SYSTEM,
        user,
        temperature=0.85,
        max_tokens=1200,
    )
    match = _YT_SEO_RE.search(raw)
    if not match:
        raise ValueError(f"Konnte YT-SEO-Output nicht parsen: {raw!r}")
    title = match.group("title").strip()
    desc = match.group("desc").strip()
    if not title or not desc:
        raise ValueError("YT-SEO Title oder Description leer.")
    return title, desc


# ---------------------------------------------------------------------------
# Eligibility Check (GPT-4o Vision)
# ---------------------------------------------------------------------------

import base64 as _base64

_ELIGIBILITY_RE = re.compile(
    r"SCORE:\s*(?P<score>\d{1,3}).*?RECOMMEND:\s*(?P<rec>go|risky|block).*?REASONING:\s*(?P<why>.+?)\s*$",
    re.DOTALL | re.IGNORECASE,
)


async def check_image_eligibility(image_bytes: bytes) -> dict[str, Any]:
    """Bewertet ein Bild via GPT-4o Vision: wie wahrscheinlich wird es von
    Pokemon-Trademark-Filtern (Seedance / Kling / Flow) blockiert?

    Returns: dict {score: int 0-100, recommend: 'go'|'risky'|'block', reasoning: str}.
    Provider (OpenAI vs Gemini) wird ueber settings.vision_provider gewaehlt.
    """
    client, vision_model = _vision_client_and_model()
    b64 = _base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    system = (
        "You are a trademark / IP filter expert. You evaluate whether an image "
        "is likely to be blocked by Pokemon-trademark detection in commercial "
        "AI video / image generators (Seedance, Kling Labs, Higgsfield, Flow).\n\n"
        "You MUST analyse the actual visual content of the attached image - "
        "different images get DIFFERENT scores. Do not return a default score.\n\n"
        "Respond strictly in this format (one line each, plain text - no JSON, "
        "no markdown):\n\n"
        "SCORE: <integer 0-100>\n"
        "RECOMMEND: <go|risky|block>\n"
        "REASONING: <one to three sentences naming SPECIFIC visual features "
        "you observed in this exact image>\n\n"
        "Score anchoring (calibrate by example):\n"
        "  0-9   - Image clearly NOT a creature (e.g. a sneaker, a landscape, "
        "an abstract pattern). RECOMMEND: go.\n"
        "  10-29 - Generic creature or fantasy character with NO Pokemon-IP "
        "markers (e.g. a realistic dragon, a wolf, a spider, original concept "
        "art unrelated to Pokemon). RECOMMEND: go.\n"
        "  30-49 - Stylized creature that COULD be confused with Pokemon but "
        "has no recognizable specific Pokemon (e.g. cute round mascot creature "
        "with no specific Pikachu/Charizard/etc. markers). RECOMMEND: go to risky.\n"
        "  50-69 - Recognizable hybrid that combines features from multiple "
        "Pokemon but is clearly a fan-made fusion, not a single trademark. "
        "RECOMMEND: risky.\n"
        "  70-89 - Strong Pokemon-IP signals: clearly recognizable Pikachu "
        "cheek-circles, Charizard wings, Gengar grin, Pokeball platform, "
        "type-icons, etc. RECOMMEND: block.\n"
        "  90-100 - Direct copy of an iconic Pokemon character (e.g. unmodified "
        "Pikachu / Charizard / Mewtwo). RECOMMEND: block.\n\n"
        "REASONING must mention SPECIFIC features YOU SEE: shape, colors, body "
        "parts, accessories. NEVER repeat the score guide verbatim."
    )

    user_messages = [
        {"type": "text", "text": "Evaluate this image for Pokemon-trademark filter risk."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    last_exc: Exception | None = None
    for attempt in range(1, _OPENAI_RETRIES + 1):
        try:
            log.warning(
                "Vision attempt %d/%d (eligibility-check, provider=%s, model=%s)",
                attempt, _OPENAI_RETRIES, settings.vision_provider, vision_model,
            )
            resp = await client.chat.completions.create(
                model=vision_model,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_messages},
                ],
                max_tokens=400,
                timeout=_OPENAI_TIMEOUT_S,
            )
            text = (resp.choices[0].message.content or "").strip()
            log.warning(
                "Vision eligibility raw output (provider=%s): %r",
                settings.vision_provider, text[:500],
            )
            m = _ELIGIBILITY_RE.search(text)
            if not m:
                raise ValueError(f"Konnte Eligibility-Output nicht parsen: {text!r}")
            score = max(0, min(100, int(m.group("score"))))
            rec = m.group("rec").lower()
            reasoning = m.group("why").strip().split("\n")[0].strip()
            log.warning(
                "OpenAI vision eligibility -> score=%d rec=%s reasoning=%r",
                score, rec, reasoning[:120],
            )
            return {"score": score, "recommend": rec, "reasoning": reasoning}
        except (APITimeoutError, APIConnectionError, httpx.TimeoutException,
                httpx.NetworkError) as exc:
            last_exc = exc
            log.warning("OpenAI vision network error attempt %d: %s", attempt, exc)
        except RateLimitError as exc:
            last_exc = exc
            log.warning("OpenAI vision rate limit attempt %d: %s", attempt, exc)
        except APIError as exc:
            last_exc = exc
            log.warning("OpenAI vision API error attempt %d: %s", attempt, exc)
        if attempt < _OPENAI_RETRIES:
            await asyncio.sleep(2 ** attempt)
    assert last_exc is not None
    raise RuntimeError(
        f"OpenAI vision eligibility-check fehlgeschlagen nach {_OPENAI_RETRIES} Versuchen: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Vision: Distinctive-Traits-Beschreibung aus einem Bild ziehen
# ---------------------------------------------------------------------------


_VISION_DESCRIBE_SYSTEM = """You are a creature-design analyst. You look at a single image of a fantasy creature (likely a Pokemon-fusion) and produce a structured Distinctive-Traits brief that downstream prompt-writers can use to generate Seedance / Kling video prompts.

Output ONE continuous paragraph, 180-260 words, in this exact shape:

A [archetype label] hybrid creature with [silhouette + posture]. Its body shows [anatomy: head, eyes, fangs, horns, scales/fur/armor, limbs, tail, wings, signature feature with concrete colors and textures]. Its colour palette: [3-5 specific colors with where they appear]. Signature feature: [the ONE most striking detail]. Mood and personality: [tone]. Primary action archetype: [one of: high-speed flight, blade combat, telekinetic / psychic magic, predatory hunt, brute destruction, summoning, energy bombardment, stealth / teleport, aquatic predator, arcane caster, etc.]. Implied signature ability: [name it in ALL CAPS, with the body part it emanates from and the concrete VFX color and texture, e.g. 'VOID LANCE - violet beam erupting from a third eye that carves a glowing geometric scar in the air'].

Hard rules:
- Describe ONLY what is visible in the image. Do not invent features that contradict the image.
- NEVER name any original Pokemon (no 'Charizard', 'Gengar', 'Latios', etc.). Describe by anatomy and color only.
- Use concrete adjectives, not vague ones. 'Violet' not 'purplish'. 'Cracked obsidian armor' not 'dark shell'.
- The 'Implied signature ability' must be inferred from visible cues (claws, blades, glowing eyes, energy emanations, wing-shape, body posture, weapon, halo, mark) - not invented from nothing.
- One paragraph, no headings, no bullet points."""


async def describe_creature_image(image_bytes: bytes) -> str:
    """Erzeugt eine Distinctive-Traits-aehnliche Beschreibung eines hochgeladenen
    Creature-Bildes via Vision (Provider richtet sich nach settings.vision_provider).
    Wird als Eingang fuer manuelle Step-5/6 / Action-Scene / Showcase-Image-Prompts
    genutzt, wenn der User ausserhalb der Pipeline eine Generation will."""
    if not image_bytes:
        raise ValueError("Leeres Bild.")
    client, vision_model = _vision_client_and_model()
    b64 = _base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    user_messages = [
        {"type": "text", "text": "Analyse this creature image and produce the Distinctive-Traits brief."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    last_exc: Exception | None = None
    for attempt in range(1, _OPENAI_RETRIES + 1):
        try:
            log.warning(
                "Vision attempt %d/%d (describe-creature, provider=%s, model=%s)",
                attempt, _OPENAI_RETRIES, settings.vision_provider, vision_model,
            )
            resp = await client.chat.completions.create(
                model=vision_model,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": _VISION_DESCRIBE_SYSTEM},
                    {"role": "user", "content": user_messages},
                ],
                max_tokens=700,
                timeout=_OPENAI_TIMEOUT_S,
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("Leere Vision-Antwort.")
            log.warning(
                "Vision describe-creature -> %d chars (provider=%s)",
                len(text), settings.vision_provider,
            )
            return text
        except (APITimeoutError, APIConnectionError, httpx.TimeoutException,
                httpx.NetworkError) as exc:
            last_exc = exc
            log.warning("Vision describe network error attempt %d: %s", attempt, exc)
        except RateLimitError as exc:
            last_exc = exc
            log.warning("Vision describe rate limit attempt %d: %s", attempt, exc)
        except APIError as exc:
            last_exc = exc
            log.warning("Vision describe API error attempt %d: %s", attempt, exc)
        if attempt < _OPENAI_RETRIES:
            await asyncio.sleep(2 ** attempt)
    assert last_exc is not None
    raise RuntimeError(
        f"Vision describe-creature fehlgeschlagen nach {_OPENAI_RETRIES} Versuchen: {last_exc}"
    ) from last_exc
