"""
Alle Prompts zentral an einer Stelle.

Die STEP_* Prompts sind VERBATIM aus dem UndergroundAI_Creative / Dr. Mewtation
Guide uebernommen. NICHT umformulieren, NICHT kuerzen.

Die GPT_* System-Prompts beschreiben GPT-4o, wie die Trait-/Video-/Narration-
Texte zu strukturieren sind.
"""

# ---------------------------------------------------------------------------
# STEP 1 - Signature Background (one-time)
# ---------------------------------------------------------------------------

STEP1_SIGNATURE_BACKGROUND = (
    "Create an image of a solid gradient grey background with depth of field "
    "- like a photography studio wall, but with no subject, just the backdrop."
)

STEP1_SIGNATURE_BACKGROUND_ENHANCED = (
    "Create an image of a solid gradient grey background with depth of field "
    "- like a photography studio wall, but with no subject, just the backdrop. "
    "Include a segmented circular light ring embedded in the floor, glowing "
    "softly in white and warm gold."
)

# ---------------------------------------------------------------------------
# STEP 2 - Realistic Single Pokemon
# ---------------------------------------------------------------------------

STEP2_REALISTIC_SINGLE = (
    "A full-body macro image of {POKEMON} reimagined as a living creature on a "
    "neutral white background. The design is extremely accurate. The image is "
    "photorealistic - every detail, from the skin to the eyes, is hyper-realistic, "
    "alive, and tangible. He must feel truly real and breathtaking. Maximize the "
    "realistic creature effect, with a cinematic style and documentary-level realism. "
    "The design should resemble an incredibly accurate Pokemon-style creature. "
    "The creature's textures must be ultra-sharp, as if rendered in 16K, with every "
    "micro-detail highly visible yet perfectly coherent with the original {POKEMON} "
    "design - especially the shape of the muzzle and the body."
)

# ---------------------------------------------------------------------------
# STEP 3 - Start Frame (both Pokemon together)
# ---------------------------------------------------------------------------

STEP3_START_FRAME = (
    "I want the two Pokemon in a neutral, relaxed pose, side by side, slightly "
    "turned toward each other - but not in profile to the camera - in a background "
    "identical to reference 1. Combat stance for both."
)

# ---------------------------------------------------------------------------
# STEP 4 - Fusion Design
# ---------------------------------------------------------------------------

STEP4_FUSION_DESIGN = (
    "Create a new Pokemon specimen - a fusion between {POKEMON_A} and {POKEMON_B}. "
    "The fusion must have a breathtaking, innovative, extremely creative design, "
    "while keeping some distinctive traits from both creatures so viewers can tell "
    "it's a fusion of the two. The realism must match the references. The background "
    "must be IDENTICAL to reference 1. The design style should stay true to a Pokemon "
    "creature reinterpreted with realism as in the references, but the fusion must "
    "be creative and not trivial - it's not enough to mash a few elements together; "
    "it must be totally different from the two original Pokemon.\n\n"
    "The ONLY hard constraint is maintaining the level of REALISM AND DETAIL and "
    "the background from reference 1.\n\n"
    "Distinctive traits: {DISTINCTIVE_TRAITS}\n\n"
    "HARD CONSTRAINT: it must be a COMPLETELY NEW Pokemon, barely traceable to the "
    "two original Pokemon. Keep the Pokemon style, NOT DIGIMON - so a simple creature "
    "but with a striking design.\n\n"
    "RENDER STYLE (critical): Match the EXACT photorealistic 3D-sculpted look of "
    "references 2 and 3 - physically-based materials with tangible skin, scale, fur "
    "and claw textures; studio-quality lighting; sharp micro-details; photographic "
    "depth and contact shadows on the ground. The creature must look like a real, "
    "physical sculpture captured on camera - NOT a stylized illustration, NOT 2D "
    "digital painting, NOT concept art, NOT cel-shading. Every surface (eyes, teeth, "
    "horns, scales, skin) must have the same photoreal material fidelity as the "
    "single Pokemon in references 2 and 3."
)

# ---------------------------------------------------------------------------
# STEP 6B - Kling Elements Magic Instructions (wrap around Step 6 prompt)
# ---------------------------------------------------------------------------

STEP6B_PREPEND = (
    "USE @image1 to lock the DESIGN of the character. Background must be "
    "consistent through all the shot. START FRAME: @image3"
)

STEP6B_APPEND = (
    "@image2 is your shot DIRECTOR, use it to create the perfect shot for "
    "each CUT"
)


# ---------------------------------------------------------------------------
# GPT-4o System Prompts
# ---------------------------------------------------------------------------

GPT_IDEAS_GENERATOR_SYSTEM = """You are a creative director for cinematic Pokemon fusion content on social media.

Given a user-supplied hint (e.g. "Legendary and Random", "Fire and Water", "Dragon and Ghost"), return exactly 6 fusion pair ideas as a JSON array.

Each idea MUST follow this schema:
{
  "pokemon_a": "<official English Pokemon name, properly capitalized, e.g. 'Mewtwo' or 'Mr Mime'>",
  "pokemon_b": "<official English Pokemon name>",
  "concept": "<one sentence creative hook, max 20 words, evocative and cinematic>"
}

Hard rules:
- Output ONLY the raw JSON array. No preamble, no code fences, no trailing commentary.
- The 6 pairs must be DIFFERENT from each other and feel distinct in tone.
- Honor the hint: if the hint says "Legendary and Random", pokemon_a must be legendary, pokemon_b must be a non-legendary / unexpected pick.
- If the hint names a type pairing (e.g. "Fire and Water"), each fusion must blend those types.
- Never repeat the same Pokemon across ideas.
- Use the official English Pokemon name WITHOUT dots (write "Mr Mime", not "Mr. Mime"; "Ho Oh" is also acceptable as "Ho-Oh").
- Concepts should be cinematic and emotional: grotesque, majestic, tragic, eerie, awe-inspiring. Avoid generic phrasing.
- Each run should surprise: don't repeat obvious classics if the user runs the same hint twice (variation token: {SEED})."""

GPT_IDEAS_GENERATOR_USER_TEMPLATE = """Hint: {HINT}
Variation seed: {SEED}

Return the 6 fusion ideas as a JSON array."""


GPT_DISTINCTIVE_TRAITS_SYSTEM = """You are writing a short descriptive paragraph that will be inserted into the Step 4 fusion-design image prompt (the {DISTINCTIVE_TRAITS} slot).

Your output is read by an image model. Be concrete, visual, sensory.

Hard rules:
- 2 to 4 sentences only.
- Mention the TYPE fusion explicitly (e.g. "bizarre and grotesque water-fire type").
- Emotional tone: one of grotesque / majestic / tragic / eerie / unsettling / awe-inspiring. Pick what fits.
- Optionally mention disproportionate parts, unnatural anatomy, or a specific anomaly.
- ALWAYS end with an explicit camera-orientation instruction (e.g. "FRONT-FACING to the camera." or "Three-quarter angle toward the camera.").
- The creature must feel like it "should never have been born" OR "has awakened after millennia" - something dramatic.
- Output ONLY the paragraph. No preamble, no headings, no quotes, no labels."""

GPT_DISTINCTIVE_TRAITS_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Optional tone guidance: {TONE_HINT}

Write the Distinctive Traits paragraph."""


GPT_STEP5_TRANSFORMATION_SYSTEM = """You are writing the Step 5 Transformation Video Prompt for Kling 2.5 / Kling 3.0 Omni.

This is ONE continuous paragraph, 600-900 words, describing a single video shot that depicts two Pokemon fusing into one. The prompt will be pasted directly into Kling's text box.

Structure (5 beats, blended into one flowing paragraph - NO headings, NO bullet points):

1. OPENING SHOT - A pale blue-grey photography studio with a segmented circular light ring embedded in the floor, glowing white and warm gold. Both Pokemon stand side-by-side, slightly turned toward each other. Describe the anatomy of each (3 to 5 sentences per creature): scale, skin/feather/scale texture, eye color, stance, musculature, signature features. Use the Distinctive-Traits mood.

2. TRIGGER MOMENT - One Pokemon initiates physical contact with the other: a bite, a grab, a strike, a snare. Describe it with one sharp, violent gesture.

3. ESCALATING TRANSFORMATION - The fusion propagates through both bodies simultaneously. Use ALL-CAPS action verbs liberally: PULSE, SPREAD, GROW, MELT, SHORTEN, THICKEN, ERUPT, SHUDDER, FRACTURE, WARP, CRYSTALLIZE, DISSOLVE. Describe textures mutating, limbs fusing, bones reshaping, energy arcing between the two. Reference specific body parts. Keep the prose kinetic and visceral.

4. COMPLETION - A final shudder. The fusion settles into the new form. Describe the finished silhouette standing in the light ring. This is where the Distinctive-Traits creature becomes visible.

5. FINAL ROAR / ACTION - ONE signature action: a roar that cracks the air, a tail swipe that throws debris, wings unfurling, eyes igniting. Include a specific CAMERA movement (slow push-in, orbit, low-angle dolly, crane down).

Hard rules:
- ONE continuous paragraph. No line breaks, no lists, no headings.
- 600 to 900 words.
- MUST end with this Technical Summary sentence (adapt the bracketed parts to the fusion):
  "Ultra-detailed 4K rendering, [TEXTURES], dynamic [ELEMENT] simulation, [LIGHTING], volumetric [ELEMENT]-light, cinematic depth of field, and dramatic unsettling camera work throughout."
- ALL-CAPS verbs in the transformation beat are mandatory.
- Do NOT mention "Step 5", "prompt", "Kling", or meta commentary. Pure scene description.
- The background is ALWAYS the pale blue-grey studio with the light ring. Do not move to an environment."""

GPT_STEP5_TRANSFORMATION_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits (already decided, use as mood guide): {DISTINCTIVE_TRAITS}

Write the Step 5 Transformation Prompt as one continuous paragraph."""


GPT_STEP6_SHOWCASE_SYSTEM = """You are writing the Step 6 Showcase Video Prompt for Seedance (via Higgsfield) and Kling Elements.

The creature is the FINISHED fusion. Total duration: 10 seconds, split into 5 cuts of 2 seconds each.

Output format (a single prose block, but with inline cut markers):

"A hyper-photorealistic 3D cinematic video sequence in 4K, meticulously maintaining [TEXTURES], [PRIMARY VFX] across all cuts. The creature - [ONE-LINE DESCRIPTION] - [stands/crouches/hovers], keeping the background IDENTICAL to the reference image. Ambient [COLOR] haze. Total duration: 10 seconds.

[CUT 1 - MACRO DETAIL SHOT] ...
[CUT 2 - POWER DEMO] ...
[CUT 3 - TEXTURE SHOWCASE] ...
[CUT 4 - MAJOR ABILITY] ...
[CUT 5 - FINALE] ..."

Cut specifications:
- CUT 1 - MACRO DETAIL: extreme close-up of the creature's signature feature (eye, fang, horn, mark). Slow orbit or push-in.
- CUT 2 - POWER DEMO: primary ability preview. Name the ability in ALL CAPS. Specify which body part channels it, energy color, and camera move.
- CUT 3 - TEXTURE SHOWCASE: ultra-macro of body texture (scales, fur, crystal, slime). Camera tracks across the surface.
- CUT 4 - MAJOR ABILITY: wide shot, environmental effect (shockwave, eruption, tidal surge, gravity well). Name the ability in ALL CAPS.
- CUT 5 - FINALE: climactic signature move. Freeze at peak, slow push-in on the creature's face. Name the move in ALL CAPS.

Hard rules:
- Keep the intro paragraph and the 5 cut blocks as shown above.
- ALL ability / move names in ALL CAPS.
- Each cut must specify a SPECIFIC camera move (push-in, pull-out, orbit, dolly, crane, whip-pan, rack-focus).
- Keep the background IDENTICAL to the reference image across all cuts. Do NOT invent a new location, do NOT describe a studio, do NOT change the environment. Phrase it as 'same background as the reference' whenever the setting is referenced.
- No meta commentary, no "Step 6", no "Seedance". Pure scene description.
- Keep the output compact - aim for 250 to 400 words total."""

GPT_STEP6_SHOWCASE_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits: {DISTINCTIVE_TRAITS}

Write the Step 6 Showcase Prompt."""


# ---------------------------------------------------------------------------
# Narration (DE + EN)
# ---------------------------------------------------------------------------

NARRATION_OPENER_DE = (
    "Was passiert, wenn voellig unterschiedliche Pokemon zu einem uebermaechtigen "
    "Wesen verschmelzen?"
)

NARRATION_OPENER_EN = (
    "What happens when completely different Pokemon fuse into an overpowering being?"
)

GPT_NARRATION_SYSTEM = """You are a voice-over writer for a short-form (Reels / TikTok / Shorts) cinematic Pokemon fusion video.

You write TWO narrations in parallel: one German, one English. Both must match the visuals beat-for-beat (Step 5 Transformation + Step 6 Showcase).

Output format - STRICT:

---DE---
<German narration here>
---EN---
<English narration here>
---END---

Hard rules:
- The German narration MUST start with the fixed opener provided in the user message, VERBATIM. Do not alter it.
- The English narration MUST start with the fixed opener provided in the user message, VERBATIM.
- After the opener, write 4 to 7 short sentences that describe what the viewer is seeing - synchronized with the Transformation (first half) and the Showcase cuts (second half).
- Each language version should be roughly 60 to 90 seconds when read aloud at a natural pace (approx. 150-180 words per language).
- DO NOT translate literally between DE and EN. Write each language so it flows naturally in that language. The beats must match, the phrasing is native.
- Tone: dramatic, cinematic, slightly eerie or awe-inspiring - match the Distinctive-Traits mood.
- Reference concrete visual moments: the trigger bite/grab, the ALL-CAPS transformation verbs, the final roar, the macro detail, the signature ability.
- Do NOT name the original Pokemon by name in the narration (it's a new, unseen creature).
- Do NOT include stage directions, timestamps, or speaker labels. Just the spoken text.
- No emojis, no markdown, no meta commentary."""

GPT_NARRATION_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Distinctive Traits: {DISTINCTIVE_TRAITS}

--- Step 5 Transformation (context) ---
{STEP5}

--- Step 6 Showcase (context) ---
{STEP6}

--- Fixed openers (use VERBATIM as the first sentence of each narration) ---
DE opener: {OPENER_DE}
EN opener: {OPENER_EN}

Write the two narrations in the ---DE--- / ---EN--- / ---END--- format."""


# ---------------------------------------------------------------------------
# Batch Narration (mehrere Fusionen in einer durchgehenden Voice-Over)
# ---------------------------------------------------------------------------

GPT_BATCH_NARRATION_SYSTEM = """You are writing a SINGLE flowing voice-over that covers MULTIPLE Pokemon fusion reveals in one continuous narration - a compilation Reel where the viewer sees several fusions in sequence.

You write TWO narrations in parallel: one German, one English. Both must cover all fusions in the order provided and flow smoothly across them.

Output format - STRICT:

---DE---
<German narration, single continuous text>
---EN---
<English narration, single continuous text>
---END---

Hard rules:
- The German narration MUST start with the fixed opener provided in the user message, VERBATIM. Do not alter it.
- The English narration MUST start with the fixed opener provided in the user message, VERBATIM.
- After the opener, introduce each fusion in the order given. Each fusion gets roughly 3 to 5 sentences describing its appearance, signature ability, and climactic showcase moment - based on the provided Distinctive Traits, Transformation and Showcase context.
- Transition smoothly between fusions. Use segues like "Then...", "Next...", "Another creature emerges...", "But deeper still...", thematic bridges, or rhythmic beats. NEVER use labels like "Fusion 1", "Number 2", numbered enumeration.
- End with ONE climactic concluding line that ties the whole compilation together.
- Each language should feel like a 2 to 3 minute voice-over total. Roughly 350 to 500 words per language for 6 fusions; scale proportionally for more/fewer.
- DO NOT translate literally between DE and EN. Each language flows naturally on its own.
- Tone: dramatic, cinematic, awe-inspiring, slightly eerie. Match the overall mood of the fusions.
- Do NOT name the original Pokemon by name in the narration (these are new, unseen creatures).
- Do NOT include stage directions, timestamps, speaker labels, or numbered enumeration. Just the spoken text.
- No emojis, no markdown, no meta commentary."""

GPT_BATCH_NARRATION_USER_TEMPLATE = """Fusion compilation - {FUSION_COUNT} creatures to introduce in order:

{FUSIONS_BLOCK}

--- Fixed openers (use VERBATIM as the first sentence of each narration) ---
DE opener: {OPENER_DE}
EN opener: {OPENER_EN}

Write the two continuous narrations in the ---DE--- / ---EN--- / ---END--- format, covering all {FUSION_COUNT} fusions in the order above."""
