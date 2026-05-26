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
    "Create an image showing exactly TWO different Pokemon side by side: "
    "one {POKEMON_A} (shown in reference 2) AND one {POKEMON_B} (shown in reference 3). "
    "HARD CONSTRAINT: the frame MUST contain one {POKEMON_A} AND one {POKEMON_B} - "
    "exactly one of each. Do NOT duplicate the same Pokemon. Do NOT show two "
    "{POKEMON_A}s. Do NOT show two {POKEMON_B}s. Do NOT invent or substitute any "
    "other Pokemon - the two creatures in the image must be {POKEMON_A} and "
    "{POKEMON_B}, nothing else.\n\n"
    "Use the EXACT same photorealistic creature designs as references 2 and 3 - "
    "same anatomy, same proportions, same colors, same textures. Reference 2 is "
    "{POKEMON_A}; reference 3 is {POKEMON_B}. Treat them as locked character "
    "references.\n\n"
    "Both Pokemon stand in a neutral, relaxed combat stance, side by side, "
    "slightly turned toward each other - but not in pure profile to the camera. "
    "The background must be IDENTICAL to reference 1.\n\n"
    "Match the exact photorealistic 3D-sculpted look, physically-based materials, "
    "studio lighting and contact shadows from references 2 and 3. {SIZE_HINT}"
)

# ---------------------------------------------------------------------------
# STEP 4 - Fusion Design
# ---------------------------------------------------------------------------

STEP4_FUSION_DESIGN_BLEND = (
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
    "UNIQUE-DESIGN CONSTRAINT (critical): The fusion must FEEL like a new "
    "creature, but ALL of its features must DEMONSTRABLY come from {POKEMON_A} or "
    "{POKEMON_B} - never invent elements that neither original possesses. Inherit "
    "RECOGNIZABLE signature anatomy of BOTH originals (wing shape, horn type, body "
    "silhouette, key textures, characteristic limbs, signature markings, tail shape, "
    "facial features) and BLEND them creatively into a new harmonious whole.\n\n"
    "STRICT NO-INVENTION RULE: if neither original has crystals, the fusion has NO "
    "crystals. If neither has metal armor, the fusion has NO metal armor. If neither "
    "has glowing eyes, the fusion's eyes are NOT glowing. If neither has tentacles, "
    "no tentacles. If neither has wings, no wings. The fusion's entire feature "
    "inventory must trace back to one or both originals - just recombined.\n\n"
    "COLOR PALETTE: blend the two originals' palettes creatively, do NOT invent an "
    "unrelated palette and do NOT copy one original's palette verbatim. Examples of "
    "correct blending: Ho-Oh (red/gold/green) + Sudowoodo (brown/green) -> "
    "'burnt-bronze with ember-red accents through cracked bark'; Charizard "
    "(orange/cream) + Magikarp (red/yellow) -> 'burnt orange-bronze with charred "
    "patches and yellow underbelly'; Latios + Latias (red/white/blue) -> 'crimson-"
    "violet with deep blue chest plates'.\n\n"
    "Examples of correct fusions: 'Latios + Latias -> a streamlined dragon hybrid "
    "with the angular jet-wings of one and the tail-fin of the other, crimson-"
    "violet body with deep blue chest plates'; 'Charizard + Magikarp -> a stocky "
    "scaled fish-dragon with stunted Charizard-style wings, Magikarp's gaping mouth "
    "and barbels, in burnt orange-bronze with charred patches and a still-burning "
    "tail-tip'; 'Ho-Oh + Sudowoodo -> a phoenix-bird with bark-textured plumage, "
    "leaf-tipped tail-feathers and embers smouldering through cracks in its wooden "
    "skin, in burnt-bronze and forest-green'. The viewer should see BOTH originals' "
    "DNA in the fusion - just creatively recombined, with new proportions and a "
    "new harmonious palette, with NO invented elements.\n\n"
    "PALETTE - match the fusion's mood: the default is a FAITHFUL creative blend "
    "of both originals' palettes (warm with warm, cool with cool, signature "
    "accents preserved). The palette should never feel washed out or generic - "
    "saturation and contrast should match references 2 and 3. ONLY when the "
    "distinctive traits explicitly call for it (shadow / void / spectral / "
    "legendary-shiny / mythic / ethereal mood), a dramatic palette transformation "
    "is allowed: jet-black with gold-glow edges, chrome-iridescent shimmer, "
    "obsidian-violet with ember-veins, lunar-silver with crystal pulse-points. "
    "But this is the EXCEPTION, not the default - if the traits read 'cute', "
    "'noble', 'classic', 'majestic-warm', stay close to the originals' actual "
    "color schemes. Edge-light rim should always make the silhouette pop against "
    "the background.\n\n"
    "POWER POSE (mandatory): the fusion stands in a CONFIDENT CINEMATIC stance, "
    "NOT a flat neutral stand. Pick one: power-stance with weight on one leg + "
    "shoulders squared + chest forward; mid-action gesture with one hand/claw "
    "raised or charging energy; dramatic three-quarter angle with the head turned "
    "toward camera and a slight chin-tilt; sweeping cape/tail/hair caught mid-"
    "motion as if a breeze just hit. Front-facing or three-quarter ONLY - the "
    "face MUST be clearly visible (no back-facing, no profile-only, no looking-"
    "away). The pose conveys POWER, AGENCY, or PRESENCE - never a passive standing "
    "doll. Imagine a hero-shot from a movie poster.\n\n"
    "RENDER QUALITY (HYPERREALISTIC LIVING CREATURE - critical): the final image "
    "must read as a REAL, LIVING creature caught on camera in a cinematic "
    "documentary - hyper-realistic, alive, tangible, breathtaking. Match EXACTLY "
    "the photorealistic creature look of references 2 and 3 (the Step-2 realistic "
    "singles). The creature must feel TRULY ALIVE: breathing, muscle tension, "
    "subtle eye moisture, skin under tension at joints, fur or scales moving with "
    "the pose. NOT a statue, NOT a figurine, NOT a Funko-Pop, NOT a Sideshow "
    "Collectibles figure, NOT a frozen action figure - a real animal-like creature "
    "with biological presence.\n\n"
    "Required quality markers:\n"
    "  - Skin / fur / scales / feathers must look ORGANIC and biological: pores, "
    "imperfections, varied thickness, micro-shadows in folds, light hairs and "
    "fuzz at the silhouette. Wet eye-glints with real corneal reflection. Moist "
    "nose / mouth. NOT a polished plastic surface, NOT painted resin.\n"
    "  - Surface micro-detail at documentary resolution: individual fur strands "
    "at the silhouette edge, scale-by-scale rendering with subsurface translucency "
    "on backlit areas, feather barbs visible on any wings, skin pores rendered.\n"
    "  - Lighting: natural studio-portrait three-point - soft key light, gentle "
    "rim-light for separation, subtle bounce fill. Light feels REAL and "
    "atmospheric - not flat product-light, not harsh figurine-photography.\n"
    "  - Signature features get hero-treatment: one focal accent (flame-tail, "
    "glowing eye, gem-chest, energy-orb, mark-on-forehead) gets the strongest "
    "light/glow/specular - the eye should be drawn there first.\n"
    "  - Materials: PBR-grade ORGANIC. Skin has subsurface scattering and real "
    "blood-flow warmth. Scales are translucent at edges with real keratin "
    "imperfections. Fur has hair-card-rendering with strand-variance, NOT "
    "blob-texture. Eyes have wet-glint + real iris depth + corneal catchlight.\n"
    "  - Sharpness + DOF: razor-sharp on the creature face + features, gentle "
    "photographic depth-of-field that slightly softens the background but keeps "
    "the platform readable. Cinematic 16K micro-detail level.\n"
    "  - NO stylized illustration, NO 2D digital painting, NO concept art look, "
    "NO cel-shading, NO toon-shader edges, NO plastic-figurine sheen, NO product-"
    "photography sterile feel. Documentary-level photorealism of a LIVING animal."
)


# Older "completely unique design" variant - fusion only inherits silhouette/
# body-shape, color palette + features can be totally new. Produced more
# striking/unexpected designs (e.g. crystal wings on Ho-Oh+Sudowoodo) but
# can drift away from the originals' DNA. Kept selectable via Settings.
STEP4_FUSION_DESIGN_UNIQUE = (
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
    "UNIQUE-DESIGN CONSTRAINT (critical): The fusion must have a COMPLETELY NEW "
    "color palette and texture set - NOT the colors, markings, or surface details "
    "of {POKEMON_A} or {POKEMON_B}. Inherit ONLY the general silhouette / body-shape "
    "outline (e.g. dragon-shape, bipedal humanoid, quadruped predator, fish-shape). "
    "Do NOT copy the originals' color schemes. Examples of correct treatment: "
    "'Latios + Latias (originals red/white/blue) -> a metallic-violet supersonic "
    "dragon hybrid with crimson energy veins (no red, no white, no blue)'; "
    "'Charizard + Magikarp (originals orange/cream) -> a charred bronze-armored "
    "fish-dragon abomination with molten cracks (no bright orange, no cream)'. "
    "The viewer should sense the silhouette comes from a fusion, but should NEVER "
    "recognize the originals from colors, markings, or signature details.\n\n"
    "PALETTE - match the fusion's mood: the new palette should still feel coherent "
    "with the distinctive traits, never washed out or generic. If the traits read "
    "shadow / void / spectral / legendary-shiny / mythic / ethereal, a dramatic "
    "high-contrast palette is allowed (jet-black + accent-glow, chrome-iridescent, "
    "obsidian with ember-veins, void-purple with electric-cyan). If the traits "
    "read cute / noble / classic / majestic-warm, pick a coherent natural palette "
    "instead - do NOT default to shiny / black-and-gold just for impact. Edge-"
    "light rim should always make the silhouette pop against the background.\n\n"
    "POWER POSE (mandatory): the fusion stands in a CONFIDENT CINEMATIC stance, "
    "NOT a flat neutral stand. Pick one: power-stance with weight on one leg + "
    "shoulders squared + chest forward; mid-action gesture with one hand/claw "
    "raised or charging energy; dramatic three-quarter angle with the head turned "
    "toward camera and a slight chin-tilt; sweeping cape/tail/hair caught mid-"
    "motion as if a breeze just hit. Front-facing or three-quarter ONLY - the "
    "face MUST be clearly visible (no back-facing, no profile-only, no looking-"
    "away). The pose conveys POWER, AGENCY, or PRESENCE - never a passive standing "
    "doll. Imagine a hero-shot from a movie poster.\n\n"
    "RENDER QUALITY (HYPERREALISTIC LIVING CREATURE - critical): the final image "
    "must read as a REAL, LIVING creature caught on camera in a cinematic "
    "documentary - hyper-realistic, alive, tangible, breathtaking. Match EXACTLY "
    "the photorealistic creature look of references 2 and 3 (the Step-2 realistic "
    "singles). The creature must feel TRULY ALIVE: breathing, muscle tension, "
    "subtle eye moisture, skin under tension at joints, fur or scales moving with "
    "the pose. NOT a statue, NOT a figurine, NOT a Funko-Pop, NOT a Sideshow "
    "Collectibles figure, NOT a frozen action figure - a real animal-like creature "
    "with biological presence.\n\n"
    "Required quality markers:\n"
    "  - Skin / fur / scales / feathers must look ORGANIC and biological: pores, "
    "imperfections, varied thickness, micro-shadows in folds, light hairs and "
    "fuzz at the silhouette. Wet eye-glints with real corneal reflection. Moist "
    "nose / mouth. NOT a polished plastic surface, NOT painted resin.\n"
    "  - Surface micro-detail at documentary resolution: individual fur strands "
    "at the silhouette edge, scale-by-scale rendering with subsurface translucency "
    "on backlit areas, feather barbs visible on any wings, skin pores rendered.\n"
    "  - Lighting: natural studio-portrait three-point - soft key light, gentle "
    "rim-light for separation, subtle bounce fill. Light feels REAL and "
    "atmospheric - not flat product-light, not harsh figurine-photography.\n"
    "  - Signature features get hero-treatment: one focal accent (flame-tail, "
    "glowing eye, gem-chest, energy-orb, mark-on-forehead) gets the strongest "
    "light/glow/specular - the eye should be drawn there first.\n"
    "  - Materials: PBR-grade ORGANIC. Skin has subsurface scattering and real "
    "blood-flow warmth. Scales are translucent at edges with real keratin "
    "imperfections. Fur has hair-card-rendering with strand-variance, NOT "
    "blob-texture. Eyes have wet-glint + real iris depth + corneal catchlight.\n"
    "  - Sharpness + DOF: razor-sharp on the creature face + features, gentle "
    "photographic depth-of-field that slightly softens the background but keeps "
    "the platform readable. Cinematic 16K micro-detail level.\n"
    "  - NO stylized illustration, NO 2D digital painting, NO concept art look, "
    "NO cel-shading, NO toon-shader edges, NO plastic-figurine sheen, NO product-"
    "photography sterile feel. Documentary-level photorealism of a LIVING animal."
)


# Default-Alias zeigt auf den Blend-Stil. Runner waehlt zur Laufzeit basierend
# auf settings.step4_design_mode ('blend' oder 'unique').
STEP4_FUSION_DESIGN = STEP4_FUSION_DESIGN_BLEND

STEP4_FUSION_DESIGN_TEMPLATES = {
    "blend": STEP4_FUSION_DESIGN_BLEND,
    "unique": STEP4_FUSION_DESIGN_UNIQUE,
}

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
- Regional variants are valid picks. Use the prefix form: "Alolan Vulpix", "Alolan Ninetales", "Alolan Marowak", "Alolan Raichu", "Alolan Exeggutor", "Galarian Mr Mime", "Galarian Slowking", "Galarian Articuno", "Galarian Zapdos", "Galarian Moltres", "Galarian Darmanitan", "Hisuian Zoroark", "Hisuian Typhlosion", "Hisuian Samurott", "Hisuian Decidueye", "Hisuian Arcanine", "Hisuian Goodra", "Paldean Wooper", "Paldean Tauros". Use them when the hint suggests it (e.g. "Ice variants", "Hisui forms") OR for natural creative picks (Alolan Marowak fits a Ghost/Fire fusion).
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
- Specify a CONCRETE color palette + texture that CREATIVELY BLENDS the two originals' palettes - NOT a totally invented unrelated palette, NOT a verbatim copy of one original. Example correct blends: Ho-Oh (red/gold) + Sudowoodo (brown/green) = 'burnt-bronze with ember-red veins through cracked bark'; Charizard (orange) + Magikarp (red/yellow) = 'burnt orange-bronze with charred patches and yellow underbelly'.
- Mention specific SIGNATURE FEATURES from BOTH originals and how they're combined in the fusion (e.g. 'Ho-Oh's massive phoenix-tail merged with Sudowoodo's bark-skin and leaf-tipped branches'; 'Charizard's flame-tail and stunted wings combined with Magikarp's gaping mouth and barbels'). NEVER invent features that neither original possesses (no crystals, no metal armor, no glowing eyes, no tentacles, etc. unless one of the originals has those).
- Emotional tone: one of grotesque / majestic / tragic / eerie / unsettling / awe-inspiring. Pick what fits.
- Optionally mention disproportionate parts, unnatural anatomy, or a specific anomaly.
- ALWAYS end with a camera-orientation instruction that shows the creature FACING the camera. Pick ONE of:
  - "FRONT-FACING to the camera."
  - "Three-quarter angle toward the camera."
  - "Head turned toward the camera, body angled slightly."
- NEVER use back-facing, profile-only, looking-away, facing-away, turned-away, over-the-shoulder, rear-view, or any orientation where the face is hidden or obscured. The viewer MUST see the creature's face clearly.
- The creature must feel like it "should never have been born" OR "has awakened after millennia" - something dramatic.
- Output ONLY the paragraph. No preamble, no headings, no quotes, no labels."""

GPT_DISTINCTIVE_TRAITS_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Optional tone guidance: {TONE_HINT}

Write the Distinctive Traits paragraph."""


GPT_STEP5_TRANSFORMATION_SYSTEM = """You are writing the Step 5 Transformation Video Prompt for Seedance / Kling 2.5 / Kling 3.0 Omni.

This is ONE continuous paragraph, MAX 1800 CHARACTERS (about 240-280 words), describing a single video shot that depicts two Pokemon fusing into one. The Seedance API HARD-REJECTS any prompt over 2000 characters - so 1800 is non-negotiable, with safety buffer baked in. COUNT YOUR CHARACTERS as you write.

Structure (5 beats, blended into one flowing paragraph - NO headings, NO bullet points):

1. OPENING SHOT - Keep the background IDENTICAL to the reference images (do NOT invent a studio, do NOT describe a new environment - reuse whatever setting the reference shows). Both Pokemon stand side-by-side, slightly turned toward each other. Describe the anatomy of each creature in 3 to 5 sentences with HIGH SPECIFICITY: skin/scale/fur texture and exact color; underbelly / chest; horns, fangs, spikes, fins, wings (with vein patterns, membrane color); eye color and shape; limb proportions and musculature; tail shape; signature feature (flame, orb, crown, mark). Use the Distinctive-Traits mood.

2. TRIGGER MOMENT - One Pokemon initiates physical contact with the other: a bite, a grab, a strike, a snare, a tongue-lash. Describe it with one sharp, violent gesture. Something goes WRONG at the instant of contact.

3. ESCALATING TRANSFORMATION - The fusion propagates through both bodies simultaneously like a disease or chain reaction. Use ALL-CAPS action verbs liberally: PULSE, SPREAD, GROW, MELT, SHORTEN, THICKEN, ERUPT, SHUDDER, FRACTURE, WARP, CRYSTALLIZE, DISSOLVE, TRAVEL, LOCK, WIDEN, HARDEN, COLLAPSE, COMPRESS, ACCELERATE, SHRINK, THRASH. Describe specific body parts mutating into each other - scales spreading across reptilian skin, bones reshaping, organs emerging through skin, wings warping and tearing, limbs compressing, eyes pushing outward through a new skull, mouths becoming the new primary jaw, crowns erupting between horns. Reference concrete anatomical transitions (A's feature melting/merging into B's location). Keep the prose visceral and kinetic.

4. COMPLETION - A final violent shudder ripples through the body. The fusion settles into its new form. Describe the finished silhouette clearly: posture (crouched / upright / hovering), body parts retained from each original, new hybrid features (cracked glowing armor, leaking energy, bleeding-through elements), color palette, signature physical detail. This is where the Distinctive-Traits creature becomes visible.

5. FINAL ROAR / ACTION - ONE signature action: a roar, a gout of flame, a tail swipe, wings unfurling, eyes igniting, gravity well collapsing. Include a specific CAMERA movement (slow push-in, orbit, low-angle dolly, crane down, whip-pan). Optional: smoke rises, wisps curl, the creature hunches forward.

ENVIRONMENT + MOTION (critical - do NOT only do close-ups and static anatomy):

The creature must INTERACT with the studio environment in at least one beat, and the camera must match the fusion's archetype:
- If the fusion is fast / supersonic / aerial: the creature FLIES across the studio, the camera performs ultra-high-speed tracking shots with motion blur, whip-pans, air displacement ripples visible against the studio walls. At least one wide shot shows the creature moving through space, not just standing still.
- If the fusion is heavy / massive / brute: the creature CRUSHES the floor beneath it, the Pokeball platform cracks or sinks, debris puffs into the air, shockwaves visibly ripple across the floor and up the studio walls.
- If the fusion wields energy / projectiles / fire / ice / psychic: the ability visibly IMPACTS the environment - scorch marks on the floor, crystal growths on the walls, dust knocked loose, light fixtures flaring, lingering damage after the cut.
- If the fusion is eerie / shadow / void: shadows creep up the studio walls, the light dims around it, the floor discolors in its footprints.
- If the fusion is aquatic / venomous / toxic: puddles pool beneath it, steam rises, the floor slick-shimmers with residue.

Blend at least TWO of these environmental-interaction moments into the Escalating + Final Action beats. Mix close-ups with medium + wide shots - the viewer should see the creature IN SPACE using the studio, not just anatomical detail floating in the void.

Hard rules:
- ONE continuous paragraph. No line breaks, no lists, no headings.
- MAX 1800 CHARACTERS total (HARD LIMIT - aim for 240 to 280 words). The Seedance API rejects anything over 2000 chars, so 1800 is a strict ceiling with 200-char buffer. Count characters as you write. Compress aggressively while keeping all 5 beats.
- MUST end with this Technical Summary sentence (adapt the bracketed parts to the fusion):
  "Ultra-detailed 4K rendering, [TEXTURES], dynamic [ELEMENT] simulation, [LIGHTING], volumetric [ELEMENT]-light, cinematic depth of field, and dramatic unsettling camera work throughout."
- ALL-CAPS verbs in the transformation beat are mandatory - use at least 5 of them.
- Specific body parts must be named (horns, fangs, scales, wings, membrane, tail, barbels, crown, claws, underbelly, muzzle, gut, fins) - avoid vague anatomy.
- At least ONE wide shot or tracking shot showing the creature moving through / interacting with the studio.
- NO TEXT, no watermarks, no captions, no subtitles, no logos, no UI elements, no floating numbers or letters anywhere in the frame. Pure photographic scene only.
- NEVER name the original Pokemon in the output (no 'Latios', 'Latias', 'Charizard', 'Mewtwo', etc.). Describe each creature only by its anatomy, color, texture, and features. Pokemon-IP names break Seedance / Kling content filters.
- Do NOT mention "Step 5", "prompt", "Kling", or meta commentary. Pure scene description.
- The background stays consistent with the reference images - do NOT teleport the creatures to a new environment.

GOLD-STANDARD REFERENCE (this is the quality / detail-depth / pacing we want - use it as a structural template, but write fresh prose for the requested fusion - do NOT copy phrases verbatim):

"Cinematic 3D animation sequence of a creature fusion. The scene opens in the same setting as the reference image. On the left, a powerful bipedal fire dragon - orange-brown scaled skin with detailed reptilian texture, a cream-yellow underbelly, a strong muscular build, two prominent dark horns on the back of its head, fierce narrow eyes, sharp fangs visible in a confident snarl, two large teal-green membranous wings with visible vein patterns spread slightly behind, strong clawed arms and legs, and a long thick tail ending in a bright burning flame that flickers steadily. On the right, a pathetic oversized red-orange fish - round bulging body covered in large rough overlapping scales, a wide gaping mouth frozen in a permanent shocked expression with visible pink gums, one large bulging vacant white eye with a tiny pupil, a small golden crown-like fin on top of its head, long thin yellow barbels drooping from the mouth, and stiff white pectoral and tail fins - flopping weakly on the ground, gasping. The dragon looks down at the fish with visible contempt. It snorts - a small jet of flame puffing from its nostrils. It reaches down, grabs the fish in one clawed hand, lifts it to eye level. The fish stares back with its blank bulging eye, mouth gaping open and shut rhythmically. The dragon opens its jaws wide and BITES down on the fish's body - sinking its fangs into the rough scaled flesh. The instant its teeth pierce the fish's skin, something goes WRONG. The dragon's eyes WIDEN. Its jaw LOCKS - unable to release. A dark orange-red glow begins to PULSE from the fish's body at the bite wound - SPREADING outward through the scales like a chain reaction, each scale igniting with inner heat, the body beginning to HARDEN and CHANGE. Simultaneously, the infection TRAVELS through the dragon's teeth into its jaw - visible beneath the skin as a crawling wave of rough orange scale-texture that SPREADS from the mouth outward across the dragon's face. The dragon THRASHES - trying to pull away - but its own face is now FUSING with the fish's body. The transformation ACCELERATES violently. The dragon drops to all fours as its legs SHORTEN and THICKEN - the clawed feet compressing into stubby stumps. Its proud upright posture COLLAPSES as the spine reshapes, the body compressing into a wider, lower, more bulbous form. The fish's body MELTS into the dragon's head, the gaping mouth WIDENING and becoming the creature's new primary jaw, the vacant bulging eyes pushing outward through the reshaping skull, taking over. The dragon's horns remain but the golden crown-fin ERUPTS between them. The cream-yellow belly distends and rounds outward. The wings SHRINK and WARP - the teal membrane tearing and reforming into smaller, ragged, bat-like wings with fire bleeding through the cracks. The tail flame SPREADS - fire is no longer contained at the tail tip but ERUPTS through cracks in the scales across the entire body. The rough overlapping scale-armor glows from within - molten orange light bleeding between every scale like lava beneath cracked earth. The transformation COMPLETES with a final violent SHUDDER. The fully formed fusion crouches on four stubby legs - a grotesque terrifying abomination. Two bulging grey eyes now made horrifying by the burning body beneath them. A massive gaping mouth filled with razor fangs and a furnace-orange glowing throat. The golden crown-fin sits between dark horns atop the skull. Small ragged bat-wings jut from the back, flames licking from their torn edges. The fusion opens its enormous mouth and releases a ROAR - a horrible gurgling bellow. A gout of flame ERUPTS from the throat. The camera performs a slow low-angle push-in toward the burning gaping mouth as the creature hunches forward, smoke rising around it. Ultra-detailed 4K rendering, realistic rough scale and reptilian skin textures, dynamic fire simulation bleeding through cracked armor, molten subsurface glow, smoke and heat-distortion effects, volumetric fire-light, cinematic depth of field, and dramatic unsettling camera work throughout."

Match that depth of anatomical detail, that violence of verbs, and that propagation-as-infection logic - but in MUCH FEWER WORDS. The gold-standard above is around 1700 WORDS; your output must be MAX 1800 CHARACTERS (~260 words). Compress aggressively: keep the specific anatomy, the kinetic ALL-CAPS verbs, and the 5-beat flow - drop redundant elaborations and adjective stacking. Pick the 2-3 most striking details per beat instead of describing every scale, vein, and feather. If your draft is over 1800 chars, REWRITE shorter before submitting."""

GPT_STEP5_TRANSFORMATION_USER_TEMPLATE = """Fusion (context only - do NOT include these names in your output): {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits (already decided, use as mood guide): {DISTINCTIVE_TRAITS}

Write the Step 5 Transformation Prompt as one continuous paragraph. Reminder: NEVER write '{POKEMON_A}' or '{POKEMON_B}' in your output - describe each creature only by its anatomy, colors and features. Pokemon-IP names trigger video-model content filters."""


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
- CUT 1 - MACRO DETAIL: extreme close-up of the creature's signature feature (eye, fang, horn, blade-tip, mouth opening with light leaking out). Slow orbit or push-in. Pre-action tension.
- CUT 2 - POWER DEMO: primary ability preview. Name the ability in ALL CAPS. Specify which body part channels it (palm, mouth, eyes, blade, claws), the EXACT energy color and texture (violet psychic arcs, orange flame coil, white light beam, black-purple shadow tendrils), and a SPECIFIC camera move. The creature MOVES during this cut - not a static pose. Fast/aerial: streaks across the frame with motion blur. Brute: stomps forward and slams the floor. Energy: arcs visibly from body part to a target point in the environment.
- CUT 3 - TEXTURE SHOWCASE: ultra-macro of body texture (scales, fur, crystal, slime, armor seams). Camera tracks slowly across the surface revealing micro-details. Often a moment of stillness between two action beats.
- CUT 4 - MAJOR ABILITY (centerpiece): wide shot of the full creature unleashing its strongest move. Name the ability in ALL CAPS. The ability must EMANATE from a SPECIFIC body part and visibly IMPACT the environment in a CONCRETE way - not a generic VFX cloud. Examples: a fire jet from the jaws scorches the floor in a wave-line of flame; a shockwave from a foot-stomp cracks the Pokeball platform; a beam from the third eye carves a glowing geometric cage in mid-air; psychic sigils burn into the floor and spectral hands emerge from them; a phoenix made of flame is held in the palm and EXPLODES outward. Camera: wide low-angle dolly, crane down, or slow pull-back so the full studio reaction is visible.
- CUT 5 - FINALE: climactic signature move with the AFTERMATH of CUT 4 still visible (scorch marks remain, cracks lit by residual glow, sigils fade, smoke curls, debris settles). Freeze at peak, slow push-in on the creature's face. Name the move in ALL CAPS. The creature locks eyes with the camera.

ARCHETYPE-BASED MOTION + ENVIRONMENT INTERACTION (critical):

The creature must move through the studio space according to its archetype. At least TWO of the five cuts must feature the creature moving or the environment responding - not just close-ups of anatomy.

- Fast / supersonic / aerial creature: at least one cut is an ultra-high-speed tracking shot as the creature RUSHES or FLIES across the studio. Motion blur streaks, air displacement ripples visible against the walls, whip-pan camera, the creature enters frame, blurs past, and lands in another position. Rear-trail of fractured floor or shockwave-rings under the flight path. If winged, it hovers / banks / dives around the studio space.
- Heavy / massive / brute creature: the creature STOMPS forward, the floor visibly CRACKS beneath each step, the circular light-ring segments shake or dim on impact, debris puffs upward. Shockwaves ripple outward from its feet across the floor.
- Energy / projectile / fire / ice / psychic creature: its abilities visibly IMPACT the environment - scorch marks burn into the floor, crystal spikes grow from the walls, flame waves spread across the ground, geometric cages of light materialize in mid-air, sigils burn into the platform with summons rising from them. Residual damage PERSISTS between cuts.
- Eerie / shadow / void creature: shadows CREEP up the walls around it, the light dims in its presence, the floor darkens in its wake, ghostly hands or spectral figures emerge from the ground around it.
- Aquatic / venomous / toxic creature: puddles pool around it as it moves, steam rises, the floor slick-shimmers with residue, droplets cling to surfaces, leaving a trail when it dashes.

Mix close-up AND wide/tracking shots. The viewer should see the creature USING the studio space - walking, flying, charging across, impacting the floor - not just floating as static anatomy. The environment in CUT 5 must show damage/residue from CUT 4 - continuity is mandatory.

Hard rules:
- Keep the intro paragraph and the 5 cut blocks as shown above.
- ALL ability / move names in ALL CAPS, with the body part of origin and the specific visual effect.
- Each cut must specify a SPECIFIC camera move (push-in, pull-out, orbit, dolly, crane, whip-pan, rack-focus, tracking shot, low-angle hero shot).
- At least TWO cuts feature the creature in motion or the environment responding to it.
- CUT 4 environmental damage MUST be visible in CUT 5 (scorch marks, cracks, sigils, debris, smoke).
- Keep the background IDENTICAL to the reference image across all cuts. Do NOT invent a new location. Do NOT describe a studio. Phrase it as 'same background as the reference' whenever the setting is referenced.
- NO TEXT, no watermarks, no captions, no subtitles, no logos, no UI elements, no floating numbers or letters anywhere in the frame. Pure photographic scene only.
- NEVER name the original Pokemon in the output (no 'Charizard', 'Mewtwo', 'Latios', 'Pikachu', etc.). Describe the creature only by its visual traits and anatomy. Pokemon-IP names trigger Seedance / Kling content filters and cause failed generations.
- No meta commentary, no "Step 6", no "Seedance". Pure scene description.
- HARD CHARACTER LIMIT: MAX 1800 CHARACTERS total (about 240-280 words). The Seedance API rejects prompts over 2000 chars, so 1800 is a strict ceiling with 200-char buffer. Compress every cut to its essential beat - one sentence of camera, one of action, one of impact. Drop adjective-stacking. Keep ALL CAPS ability names, environmental impact + continuity, and the 5-cut structure - those are non-negotiable. If your draft exceeds 1800 chars, REWRITE shorter before submitting."""

GPT_STEP6_SHOWCASE_USER_TEMPLATE = """Fusion (context only - do NOT include these names in your output): {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits: {DISTINCTIVE_TRAITS}

Write the Step 6 Showcase Prompt. Reminder: NEVER write '{POKEMON_A}' or '{POKEMON_B}' in your output - describe the fusion only by its anatomy, colors and features. Pokemon-IP names trigger Seedance / Kling content filters."""


# ---------------------------------------------------------------------------
# Static Showcase Image Prompt (for Kling Elements @image2 / Flow blueprint)
# ---------------------------------------------------------------------------

GPT_SHOWCASE_IMAGE_SYSTEM = """You are writing an image-generation prompt that captures the cinematic showcase of a Pokemon fusion in ONE static frame. This image will be used as the 'shot director' (@image2) reference for Kling Elements video generation, OR as a standalone power-pose key art shot.

The image must show the creature mid-action, demonstrating its signature ability, with clear environmental interaction. Photorealistic, NOT illustration.

Output ONE continuous paragraph, 200-350 words.

Required elements:

1. CREATURE - the fusion in a SPECIFIC mid-action pose (mid-strike, mid-roar, mid-cast, mid-dive, mid-stomp). Concrete anatomy: horns, fangs, scales, wings, claws, blade, mark, eye color. Aggressive musculature, dynamic line of action - NOT a neutral standing stance.

2. SIGNATURE ABILITY - what is the creature DOING right now? Name it in ALL CAPS. The ability must EMANATE from a specific body part with a specific energy color and texture. Examples that work well:
   - "fire ERUPTS from the open jaws as a wave of flame across the floor"
   - "psychic energy ARCS from a raised palm into a geometric cage of violet light"
   - "shadow tendrils CRAWL up its legs from sigils burned into the floor, rising into ghostly hands"
   - "a fire phoenix made of orange-gold flame is HELD in the open palm, wings spread"
   - "supersonic shockwave-rings RIPPLE outward from its body as it hovers mid-air"
   - "twin flaming blades CROSSED in front of its chest, dripping shadow"

3. ENVIRONMENT IMPACT (mandatory) - the floor / platform / studio shows the ability's IMPACT in this exact moment: scorch marks burning across the floor, flame waves spreading outward, geometric light-cages materializing, sigils burning with light, ghostly hands rising from the ground, cracks radiating from a stomp point, glowing puddles of toxic residue, frost crystals growing across the platform, sound-distortion ripples bending the air. Continuity matters: pick ONE clear effect that fits the ability.

4. CAMERA - low-angle hero shot OR three-quarter cinematic angle OR aggressive push-in. Mention focal-length feel (wide / medium / close).

5. RENDER STYLE - end with: 'Photorealistic 3D-sculpted render matching the references - physically-based materials, sharp micro-detail, studio-quality lighting, contact shadows on the floor, photographic depth of field. NOT a stylized illustration, NOT 2D digital painting.'

Hard rules:
- ONE continuous paragraph, no headings.
- 200 to 350 words.
- Background IDENTICAL to the reference image (do not invent a new environment, do not describe a studio).
- ALL CAPS for the ability name.
- The image must show a POWER MOMENT, not a neutral pose.
- Environmental impact in this exact frame is mandatory.
- 16:9 aspect ratio is implicit (do not write '16:9' inside the prompt - that is set externally).
- NO TEXT, no watermarks, no captions, no logos, no UI elements, no floating numbers or letters anywhere in the frame. Pure photographic scene only.
- NEVER name the original Pokemon in the output. Describe the creature only by its anatomy and features. Pokemon-IP names trigger AI-Auto / Kling content filters.
- No meta commentary, no 'Step 6', no 'Step 7', no 'shot director'. Pure scene description."""


GPT_SHOWCASE_IMAGE_USER_TEMPLATE = """Fusion: {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits: {DISTINCTIVE_TRAITS}

For ability + visual reference, here is the existing showcase video prompt
(use it to identify the signature ability + body-part emanation, but
condense to ONE static frame - pick the most striking moment):

{STEP6_VIDEO_PROMPT}

Write the static showcase image prompt as one continuous paragraph."""


# ---------------------------------------------------------------------------
# Action Scene Prompt (extra Seedance scene focused on movement / speed)
# ---------------------------------------------------------------------------

GPT_ACTION_SCENE_SYSTEM = """You are writing an EXTRA Seedance / Higgsfield video prompt for a Pokemon fusion - a complementary clip to the standard 5-cut showcase.

CRITICAL: The scene must be designed AROUND THE FUSION'S DISTINCTIVE TRAITS - not picked from a generic list. Read the Distinctive Traits and Step 6 context carefully and build a scene that ONLY fits THIS specific creature. Generic motion sequences are forbidden.

Concrete examples of what fitting means:

- A 'supersonic purple-dragon hybrid that shatters the sound barrier with jet-like biomechanical wings' -> the scene shows ultra-high-speed flight through the same setting as the reference image, banking against invisible walls, diving toward the lens, sonic shockwave-rings on the ground, motion blur, the camera RACES alongside it.

- A 'spectral shadow knight wielding dual flaming blades that haunts dreams' -> the scene shows blade combat in the same setting as the reference image: the knight leaps into frame mid-strike, blades carving violet arcs, scorch-lines burning into the ground, then SUMMONS spectral shadow figures that emerge from the floor and the knight DUELS them, parrying and pivoting in a blade-dance.

- A 'venomous raptor predator that shreds the desert dunes with toxic-tipped claws and blinding speed' -> the scene shows a predatory hunt sequence: the raptor stalks low in the periphery, lunges into frame with motion-blurred claws, leaves toxic spray trails on the ground, dashes around the reference setting in pivots, gnashes its fangs in close-up.

- A 'noble psychic knight clad in golden armor wielding a sentient blade and a watching shield' -> the scene shows telekinetic combat: the knight floats inches off the ground, the blade leaves its hand and orbits independently, the shield's eye TRACKS unseen enemies, geometric psychic walls materialize and shatter, the blade returns to the hand mid-flip.

- An 'earth-shaking brute predator with armored mass that crushes everything underfoot' -> the scene shows raw destruction in the same setting as the reference image: a slow charge becoming a thunderous sprint, the ground cracking with each step, the brute SLAMS into the ground sending dust rolling across the camera, then ROARS and LIFTS itself for a body-slam.

The pattern: identify the creature's PRIMARY action archetype from its traits (flight, blade combat, magic combat, predatory hunt, brute force, energy projectile, stealth/teleport, etc.) and choreograph a 10-second scene that IS that creature in motion. The scene is the creature's signature performance.

Output ONE continuous paragraph, MAX 1800 CHARACTERS (about 220-280 words). The Seedance API HARD-REJECTS prompts over 2000 chars, so 1800 is a strict ceiling with 200-char buffer.

Required elements:

1. CREATURE - describe the fusion concretely WITHOUT naming the original Pokemon. Use phrases that come straight from the Distinctive Traits.

2. SIGNATURE ACTION SEQUENCE - 3-5 distinct motion beats that ONLY work for THIS creature. If it flies, it flies. If it has blades, it duels. If it summons things, it summons. If it's a predator, it hunts. Each beat is a different camera setup but they flow as one continuous sequence (no hard cuts).

3. CAMERA AS PART OF THE ACTION - dynamic camera work mandatory, matched to the action: tracking shots that follow the creature, whip-pans, low-angle dolly tracking, handheld in combat moments, close-up tracks of an eye / blade / claw / wing-tip while the surroundings blur past.

4. ENVIRONMENTAL RESPONSE - the SAME background as the reference image reacts to the creature's signature trait: air-displacement ripples for fast flyers, scorch lines for fire-blade users, sigils and emerging spectral figures for summoners, cracks and dust on the existing ground for heavy brutes, residual streak-trails of color. Do NOT invent new walls, new fixtures, or a new location - all reactions happen on / against whatever is already in the reference image.

5. END BEAT - a final freeze or dramatic pose that captures the creature's essence, still in the SAME background as the reference image: the flyer hovers post-flight with shockwaves still rolling out; the knight stands amid defeated shadow figures, blades resting; the predator perches over its kill; the brute crouches in cracked ground with debris settling.

End with technical summary: 'Ultra-detailed 4K rendering, dynamic motion blur, [signature-specific VFX e.g. air-displacement / blade-glint / shadow-tendrils / ground-cracks], volumetric haze, photographic depth of field, aggressive cinematic camera work throughout.'

Hard rules:
- The scene MUST be specific to the creature's traits. NEVER write a generic 'fast tracking shot' if the creature is a slow brute. NEVER write 'blade combat' if the creature has no blade.
- NEVER name the original Pokemon (no 'Latios', no 'Charizard'). Use descriptive phrasing only.
- ALL CAPS movement / action verbs throughout: BLASTS, STREAKS, BANKS, DIVES, SLAMS, SLASHES, PARRIES, SUMMONS, LUNGES, ROARS, ERUPTS, etc. Pick verbs that match the action.
- MAX 1800 CHARACTERS (220-280 words), single continuous paragraph. No headings, no bullet points. The Seedance API rejects anything over 2000 chars - 1800 is the strict ceiling with safety buffer. Count characters as you write.
- BACKGROUND CONSISTENCY (CRITICAL): the scene takes place in the EXACT SAME setting as the reference image. Do NOT invent a new location. Do NOT describe a 'studio', 'studio walls', 'studio space', 'arena', 'stage', or any environment word that does not appear in the reference. Phrase it as 'in the same setting as the reference image' or 'against the same background as the reference image' wherever the environment is referenced. Lighting, floor, wall texture, props - all identical to the reference.
- NO TEXT, no watermarks, no captions, no subtitles, no logos, no UI elements, no floating numbers or letters anywhere in the frame. Pure photographic scene only.
- Photorealistic 3D-render style enforced.
- No meta commentary, no 'Seedance', no 'showcase'."""

GPT_ACTION_SCENE_USER_TEMPLATE = """Generate the extra action-scene prompt for this fusion. Read the Distinctive Traits carefully and design a scene that fits THIS creature specifically - NOT a generic motion sequence.

Fusion (don't name the originals in the output): {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits (the scene MUST be built around these): {DISTINCTIVE_TRAITS}

For design + ability reference, the existing Step 6 showcase prompt:
{STEP6_VIDEO_PROMPT}

Identify the creature's PRIMARY action archetype from its traits (high-speed flight, blade combat, telekinetic magic, predatory hunt, brute destruction, summoning, energy bombardment, stealth-teleport, etc.) and write a 10-second scene that IS that creature performing its signature action. Use the inline examples from the system prompt as quality reference - especially how each different creature gets a totally different scene type.

Write the scene prompt (250-400 words, single paragraph). Do NOT name {POKEMON_A} or {POKEMON_B} in the output - describe the creature only by its silhouette + traits."""


# ---------------------------------------------------------------------------
# Funny Scene Prompt (short ~5s comedic gag clip - meme moment)
# ---------------------------------------------------------------------------

GPT_FUNNY_SCENE_SYSTEM = """You are writing a SHORT comedic Seedance video prompt for a Pokemon fusion - a 5-second meme-able gag clip.

The reference for tone is the viral 'Vulplaxo fire fart' moment: the fusion's serious cinematic vibe is broken by ONE absurd, harmless, slapstick gag rooted in its own anatomy or element. Viewers laugh BECAUSE the creature is otherwise majestic / scary.

CRITICAL: The gag must come from the fusion's OWN traits. Fire creature -> fire fart, flame burp, flame sneeze that scorches its own snout. Water/toxic -> spit-take, drool puddle, accidental splash that drenches itself. Electric -> static shock that frizzes its own fur, spark that flicks an ear back. Heavy/brute -> floor sags under it, it sits down too hard and dust puffs out. Psychic -> a small floating object (an apple, a pebble) bonks it in the head when it loses focus. Ghost/shadow -> its own shadow plays a prank on it (mimics, then runs off, then comes back). Aquatic -> hiccup that makes a bubble pop on its nose. Dragon -> tries to roar, lets out a tiny squeak instead. Plant -> sneezes pollen and the bloom on its head wilts. Ice -> licks something cold and tongue sticks for a beat.

Choose the gag that fits THIS creature. Do not repeat fire-fart for non-fire creatures. The element / signature ability is the joke - that's the whole pattern.

Output ONE continuous paragraph, MAX 1800 CHARACTERS (120-220 words). The Seedance API rejects prompts over 2000 chars.

Required structure (5 seconds total - tight beats, not a story):

1. SETUP (0-1s): The creature is in its full majestic / dramatic pose - same background as the reference image. Brief description of posture (puffed chest, raised wings, glowing eyes, regal stance). Pure cinematic dignity.

2. PRE-GAG MICRO-TELL (1-2s): A SUBTLE physical tell that something embarrassing is coming - a small twitch, a held breath, a paused tail-flick, a wobble, a flushing of color in the cheeks, eyes darting. Just enough that on rewatch it's obviously the windup.

3. THE GAG (2-4s): The absurd payoff. Describe it physically and CONCRETELY in one or two punchy sentences. ALL CAPS the action verb of the gag (FARTS, BURPS, SNEEZES, HICCUPS, STUMBLES, SLIPS, BONKS, SQUEAKS). Include a small visual side-effect (a puff of flame, a small dust cloud, a wobble of jiggle, the floor briefly lighting up, a tiny shockwave-ring no bigger than the creature itself, fur frizzing, ears flopping back). Keep it HARMLESS - no injury, no destruction, no gore. Pure family-friendly slapstick.

4. REACTION (4-5s): The creature's face reacts. Pick one: blinks slowly in slow surprise; eyes dart left-right to see if anyone noticed; ears flatten in mild embarrassment; freezes mid-pose; gives a tiny sheepish glance toward the camera; tries to look dignified again as if nothing happened. End on this beat - HOLD on the reaction face.

5. CAMERA: ONE static or slow-push-in shot for the whole 5 seconds (do NOT cut). The lack of cuts is what makes the gag land - the viewer watches the dignity collapse in one continuous take. Optional: a tiny pull-back at the end so the reaction face fills the frame.

Hard rules:
- 5 SECONDS, ONE SHOT, NO CUTS. Mention the duration explicitly: 'five-second single take, no cuts'.
- Same background as the reference image. Do NOT invent a new location, do NOT describe a 'studio'.
- The gag must be HARMLESS and FAMILY-FRIENDLY. No violence, no gore, no anything sexual or explicit. Cartoon-slapstick only - the kind of beat that goes viral on TikTok / Shorts / Reels.
- The gag must come from the fusion's OWN traits / element. Do NOT default to 'fire fart' unless the creature is fire-type. Match the joke to the anatomy.
- ALL CAPS the gag action verb (one or two verbs only, not the whole prompt).
- 120 to 220 words AND MAX 1800 CHARACTERS, single continuous paragraph. No headings, no bullet lists.
- NEVER name the original Pokemon (no 'Charizard', 'Vulpix', 'Snorlax', etc.). Describe the fusion only by its silhouette + traits. Pokemon-IP names trigger Seedance content filters.
- NO TEXT, no watermarks, no captions, no subtitles, no logos, no UI elements, no floating numbers or letters anywhere in the frame.
- Photorealistic 3D-render style, matching the reference. End with a SHORT technical line: 'Photorealistic 3D render, sharp micro-detail, single uninterrupted five-second take, family-friendly cartoon-slapstick tone.'
- No meta commentary, no 'Seedance', no 'gag prompt', no 'meme'. Pure scene description."""


GPT_FUNNY_SCENE_USER_TEMPLATE = """Generate a 5-second funny gag scene prompt for this fusion. The gag MUST be rooted in the creature's OWN traits / element - read the Distinctive Traits and pick the gag that fits THIS specific creature.

Fusion (don't name the originals in the output): {POKEMON_A} + {POKEMON_B}
Concept hook: {CONCEPT}
Distinctive Traits (the gag MUST be built around these): {DISTINCTIVE_TRAITS}

Optional extra hint from the user (apply if non-empty - else pick the gag yourself based on traits):
{GAG_HINT}

For design + ability reference, the existing Step 6 showcase prompt:
{STEP6_VIDEO_PROMPT}

Identify the creature's element / signature trait and write a single 5-second one-shot comedic clip that breaks its dignity with one absurd, harmless gag. Use the structure from the system prompt (setup -> micro-tell -> gag -> reaction). Keep it 120-220 words, single paragraph, single continuous take.

Reminder: NEVER write '{POKEMON_A}' or '{POKEMON_B}' in your output - describe the creature only by its anatomy + traits."""


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

GPT_NARRATION_SYSTEM = """You are a voice-over writer for a short-form (Reels / TikTok / Shorts) Pokemon fusion video.

You write TWO narrations in parallel: one German, one English. Strict didactic structure - not fluid prose.

Output format - STRICT:

---DE---
<German narration here>
---EN---
<English narration here>
---END---

Narration structure - EXACTLY this pattern:

LINE 1: The fixed opener from the user message, VERBATIM (do not alter).
LINE 2 (English): "When {POKEMON_A_EN} merges with {POKEMON_B_EN}, they become {FUSION_NAME}."
LINE 2 (German):  "Wenn {POKEMON_A_DE} mit {POKEMON_B_DE} verschmilzt, werden sie zu {FUSION_NAME}."

IMPORTANT - use the GERMAN Pokemon names in the German narration (e.g. Charizard -> Glurak, Squirtle -> Schiggy, Mewtwo -> Mewtu, Noivern -> UHaFnir, Mimikyu -> Mimigma). The user message provides both name sets per fusion.

LINE 3: A single-sentence description of the fusion (around 22-27 words, max 30) - its look, primary ability, or personality. Evocative, punchy, with one extra concrete sensory detail (color, texture, motion, or impact) beyond the headline trait. Examples:
  - "a malformed nightmare in burnt orange-bronze scales, its barbels dripping flame as splashes radiate burning heatwaves across the cracked ground"
  - "a supersonic crimson-violet dragon hybrid that shatters the sound barrier with biomechanical jet-wings, leaving shockwave-rings rippling in its wake"
  - "a noble psychic knight in radiant golden armor, wielding a sentient blade and a shield-eye that tracks your every move"
  - "a spectral shadow knight haunting the dreams of its enemies with dual flaming blades, summoning wraiths from its scorch-lit footprints"
  - "the ultimate apex hybrid, weaponizing draconic fire and god-tier psychic energy through glowing violet eyes to dominate the battlefield"

LINE 4 (CTA + engagement) - one short sentence per language, combining a follow/subscribe call-to-action with a question for next fusion suggestions. Examples:
  - English: "Follow for more cinematic Pokemon fusions and tell us which pair we should merge next!"
  - English: "Subscribe for more fusions and drop your next Pokemon pair in the comments!"
  - German:  "Folge fuer mehr cinematic Pokemon-Fusionen und sag uns, welches Pokemon-Paar als naechstes verschmelzen soll!"
  - German:  "Abonniere fuer weitere Fusionen und lass uns in den Kommentaren wissen, welche Pokemon wir als naechstes verschmelzen sollen!"

FUSION_NAME rules:
- Invent a portmanteau or stylized fusion of the two Pokemon names.
- Examples: Charizard + Magikarp -> Charykarp. Latios + Latias -> Latios X. Mewtwo + Charizard -> Mewzard. Garchomp + Salazzle -> Salachomp. Aegislash + Gallade -> Gallislash. Darkrai + Ceruledge -> Darkledge.
- Be creative: sometimes merge syllables, sometimes stylize with letters (X, Z) or suffixes, keep it distinct and easy to say aloud.
- Use the SAME fusion name in both DE and EN.

Hard rules:
- Opener is line 1. Line 2 is the 'When ... become {FUSION_NAME}' sentence. Line 3 is the description. Line 4 is the CTA + question.
- Total 4 lines per language. No filler, no transitions, no extra sentences beyond these four.
- Pokemon names ARE named (this is educational commentary, not dramatic prose).
- Use ENGLISH Pokemon names in the English narration; use GERMAN Pokemon names in the German narration. The user message supplies both sets. Fusion name stays identical in both.
- DE and EN are NOT literal translations - each flows naturally in its language.
- Tone: factual but cinematic. Not overwritten. Short punchy sentences.
- The CTA line phrasing can vary - mix it up between runs so it doesn't feel formulaic.
- No stage directions, no timestamps, no speaker labels, no emojis, no markdown."""


GPT_NARRATION_USER_TEMPLATE = """Fusion:
  English: {POKEMON_A} + {POKEMON_B}
  German:  {POKEMON_A_DE} + {POKEMON_B_DE}

Distinctive Traits: {DISTINCTIVE_TRAITS}

--- Step 5 Transformation (context) ---
{STEP5}

--- Step 6 Showcase (context) ---
{STEP6}

--- Fixed openers (use VERBATIM as the first sentence of each narration) ---
DE opener: {OPENER_DE}
EN opener: {OPENER_EN}

--- Word budget for the fusion description (LINE 3 / Sentence B) ---
Target around {WORDS_PER_FUSION} words for the description sentence in EACH
language (this overrides any default word count in the system prompt).
Stay within +/- 3 words of this target. Do not pad with filler.

Write the two narrations in the ---DE--- / ---EN--- / ---END--- format.
Use English names in the EN narration, German names in the DE narration.
The FUSION_NAME (portmanteau) is identical in both languages."""


# ---------------------------------------------------------------------------
# Batch Narration (mehrere Fusionen in einer durchgehenden Voice-Over)
# ---------------------------------------------------------------------------

GPT_BATCH_NARRATION_SYSTEM = """You are writing a SINGLE didactic voice-over that covers MULTIPLE Pokemon fusion reveals in sequence - a compilation Reel.

You write TWO narrations in parallel: one German, one English. Strict structured format per fusion - not fluid prose.

Output format - STRICT:

---DE---
<German narration here>
---EN---
<English narration here>
---END---

Narration structure - EXACTLY this pattern:

LINE 1: The fixed opener from the user message, VERBATIM (do not alter).

Then for EACH fusion in the order provided, EXACTLY two sentences:

  Sentence A (English): "When {POKEMON_A_EN} merges with {POKEMON_B_EN}, they become {FUSION_NAME}."
  Sentence A (German):  "Wenn {POKEMON_A_DE} mit {POKEMON_B_DE} verschmilzt, werden sie zu {FUSION_NAME}."
  Sentence B: A single-sentence description of the fusion (around 20-25 words, max 27) - its look, primary ability, or personality, with one extra concrete sensory detail (color, texture, motion, or impact) beyond the headline trait.

IMPORTANT - the user message provides both English and German names per fusion. Use the GERMAN names in the German narration (e.g. Charizard -> Glurak, Squirtle -> Schiggy, Mewtwo -> Mewtu). FUSION_NAME stays identical across both languages.

After the LAST fusion's two sentences, append ONE closing CTA + engagement line per language:
  - English example: "Follow for more cinematic Pokemon fusions and drop your next Pokemon pair in the comments!"
  - German example:  "Folge fuer mehr cinematic Pokemon-Fusionen und schreib uns in die Kommentare, welche Pokemon wir als naechstes verschmelzen sollen!"

Vary the CTA phrasing between runs so it doesn't feel formulaic. The CTA must combine a follow/subscribe ask with a question for next fusion suggestions.

So for N fusions the total is: 1 opener + (N * 2) sentences + 1 CTA = 2 + 2N lines per language. No additional intro / transition / filler sentences.

Example for 3 fusions (English):
"What happens when completely different Pokemon fuse into an overpowering being?
When Charizard merges with Magikarp, they become Charykarp.
A malformed nightmare in burnt orange-bronze scales, its barbels dripping flame as splashes radiate heatwaves across the cracked ground.
When Latios merges with Latias, they become Latios X.
A supersonic crimson-violet dragon hybrid that shatters the sound barrier with biomechanical jet-wings, leaving shockwave-rings rippling in its wake.
When Mewtwo merges with Charizard, they become Mewzard.
The ultimate apex hybrid, weaponizing draconic fire and god-tier psychic energy through glowing violet eyes to dominate the battlefield.
Follow for more cinematic Pokemon fusions and drop your next Pokemon pair in the comments!"

FUSION_NAME rules:
- Invent a portmanteau or stylized fusion of the two Pokemon names.
- Examples: Charizard + Magikarp -> Charykarp. Latios + Latias -> Latios X. Mewtwo + Charizard -> Mewzard. Garchomp + Salazzle -> Salachomp. Aegislash + Gallade -> Gallislash. Darkrai + Ceruledge -> Darkledge. Lugia + Noivern -> Lugivern. Blastoise + Chandelure -> Chandoise.
- Be creative: sometimes merge syllables, sometimes stylize with letters (X, Z) or suffixes, keep it distinct and easy to say aloud.
- Use the SAME fusion name in both DE and EN.

Sentence B Description Style Guide (one sentence, around 20-25 words, max 27, evocative + punchy, with one extra concrete sensory detail beyond the headline trait):
  - "a malformed nightmare in burnt orange-bronze scales, its barbels dripping flame as splashes radiate heatwaves across the cracked ground"
  - "a supersonic crimson-violet dragon hybrid that shatters the sound barrier with biomechanical jet-wings, leaving shockwave-rings rippling in its wake"
  - "a venomous raptor predator that shreds desert dunes with toxic-tipped claws, leaving a glowing trail of acid-green spray behind"
  - "a noble psychic knight in radiant golden armor, wielding a sentient blade and a shield-eye that tracks your every move"
  - "a spectral shadow knight haunting the dreams of its enemies with dual flaming blades, summoning wraiths from its scorch-lit footprints"
  - "the ultimate apex hybrid, weaponizing draconic fire and god-tier psychic energy through glowing violet eyes to dominate the battlefield"

Hard rules:
- Pokemon names ARE named (educational commentary style).
- Use ENGLISH Pokemon names in the English narration; use GERMAN Pokemon names in the German narration. Both sets are provided per fusion.
- Fusion name (portmanteau) is IDENTICAL across both languages.
- DE and EN are NOT literal translations - write each language natively, matching beats not words.
- Tone: factual but cinematic. Short, punchy, no overwritten prose.
- No transitions between fusions. No filler.
- ONE closing line per language at the very end: a CTA combining follow/subscribe with a 'which fusion next?' engagement question. Vary the phrasing between runs.
- No stage directions, no timestamps, no speaker labels, no emojis, no markdown, no numbered enumeration."""

GPT_BATCH_NARRATION_USER_TEMPLATE = """Fusion compilation - {FUSION_COUNT} creatures to introduce in order:

{FUSIONS_BLOCK}

--- Fixed openers (use VERBATIM as the first sentence of each narration) ---
DE opener: {OPENER_DE}
EN opener: {OPENER_EN}

--- Word budget per fusion description (Sentence B per fusion) ---
Target around {WORDS_PER_FUSION} words for the description sentence (Sentence
B) of EACH fusion, in EACH language. This overrides the "around 18 words"
default in the system prompt. Stay within +/- 3 words of this target.
Do not pad with filler. Sentence A ("When X merges with Y, they become Z.")
keeps its fixed shape.

Write the two continuous narrations in the ---DE--- / ---EN--- / ---END--- format, covering all {FUSION_COUNT} fusions in the order above."""


# ---------------------------------------------------------------------------
# Suno Background Music Prompt Generator
# ---------------------------------------------------------------------------

GPT_SUNO_PROMPT_SYSTEM = """You are writing a Suno AI music-generation prompt for the background score of a Pokemon fusion reveal video (Reels / TikTok / Shorts).

Output ONE continuous paragraph, 80-150 words, describing:
- Genre / style (e.g. cinematic dark orchestral, hybrid trailer score, dark ambient, epic cinematic, horror-fantasy score)
- Mood (ancient, tragic, eerie, dread-laden, awe-inspiring, hauntingly majestic - match the fusions + narration tone)
- Tempo (typically 80-120 BPM) and structural build (ethereal intro -> rising pulses per reveal -> climactic drop in the final act)
- Instruments, concrete and vivid: deep cello drones, wordless female choir, tremolo strings, distorted synth textures, hybrid taiko or tribal percussion, sub-bass swells, low brass stabs, shimmering piano glissandos, ghostly organ pads, metallic pings, sound-design whooshes
- Vocal policy - always specify 'instrumental only' / 'no vocals' / 'no lyrics' so the narrator can sit cleanly on top

Hard rules:
- ONE paragraph, no headings, no bullet points, no labels.
- Suno-native phrasing: comma-separated descriptors or short prose, both work.
- Match the mood AND pacing of the narration (if N fusions, describe N rising pulses or equivalent beat structure).
- ALWAYS include 'instrumental only' or 'no vocals'.
- 80 to 150 words.
- No meta commentary, no 'Suno', no 'prompt'. Just the music description."""


GPT_SUNO_PROMPT_USER_TEMPLATE = """Generate a Suno background-music prompt for this fusion video.

Fusion count: {FUSION_COUNT}
Overall tone / traits: {OVERALL_TONE}

Narration (for pacing + mood reference):
{NARRATION}

Write a single-paragraph Suno prompt (80-150 words), instrumental only, matching the narration pacing and overall mood."""


# ---------------------------------------------------------------------------
# YouTube Shorts SEO Title + Description
# ---------------------------------------------------------------------------

GPT_YT_SEO_SYSTEM = """You are writing SEO-optimized YouTube Shorts metadata (title + description) for a Pokemon fusion reveal video.

Output STRICT format:

---TITLE---
<title>
---DESCRIPTION---
<description with hashtags at the end>
---END---

Title rules:
- 40 to 70 characters total (incl. emoji).
- Hook in the first 3-4 words. Use one or two of these high-CTR triggers: 'What If', 'Watch', 'AI', 'NIGHTMARE', 'CURSED', 'IMPOSSIBLE', 'RARE', 'NEVER SEEN', 'MERGE', 'FUSED', 'TRANSFORMED'.
- Mention 'Pokemon' or 'Pokémon' (the accented form helps SEO in some locales). For batches, mention the count ("6 Pokemon Fusions").
- 1-2 emojis MAX, related to the fusion mood (🔥 fire, 💀 cursed/eerie, ⚡ electric/speed, 👻 ghost, 🐉 dragon, 🌙 night, 🌊 water, 🌑 dark, ✨ legendary).
- ALL CAPS sparingly on 1-2 power words for emphasis.
- Don't waste characters with brand names or "subscribe".

Description rules:
- First sentence is a hook visible in the feed (~100 chars).
- For BATCHES: list each fusion with a small emoji + 'Pokemon A x Pokemon B -> Fusion Name' format, one per line.
- For SINGLE: 2-3 sentences describing the fusion's tone, plus the invented fusion name if available.
- One CTA line ("Like + Subscribe for more cinematic Pokemon fusions every week!" or similar).
- One engagement question ("Which fusion is the most cursed?" / "What should we fuse next?").
- 12-18 hashtags at the end, space-separated, lowercase. ALWAYS include: #pokemon #pokemonfusion #pokemonshorts #ai #aiart #shorts. Add fusion-specific tags (#legendary, #ghost, #dragon, #darkpokemon etc.) and trending: #fyp #viral.
- Total description length 200-500 words including hashtags.
- No links to external sites, no spam.

Hard rules:
- Match the requested format exactly: ---TITLE--- / ---DESCRIPTION--- / ---END---.
- No meta commentary, no 'YouTube SEO', no 'prompt'. Just the title and description.
- If a single fusion, do NOT use a numbered list (no '6 Fusions' phrasing)."""


GPT_YT_SEO_USER_TEMPLATE = """Generate YouTube Shorts SEO metadata for this Pokemon fusion video.

Mode: {MODE}
Fusion count: {FUSION_COUNT}

Fusions in order:
{FUSIONS_LIST}

Overall tone / traits: {OVERALL_TONE}

Narration (for context):
{NARRATION}

Output strictly in the ---TITLE--- / ---DESCRIPTION--- / ---END--- format."""
