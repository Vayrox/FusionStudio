# Fusion Auto

Automatisierte Pipeline für cinematic Pokémon-Fusion-Videos nach dem UndergroundAI_Creative / Dr. Mewtation Workflow.

## Was es macht

Pipeline (bis Step 4) pro approved Fusion:

1. Pokémon-Referenzbilder via PokeAPI (official artwork) cachen
2. **Step 2A/2B** — Realistic Single für Pokémon A + B (AI-Auto Nano Banana Pro 4K)
3. **Step 3** — Start Frame (beide zusammen im Signature-Background)
4. GPT-4o schreibt Distinctive-Traits-Paragraph
5. **Step 4** — 5 Fusion-Design-Varianten
6. GPT-4o schreibt Step 5 (Kling Transformation) + Step 6 (Seedance Showcase) Prompts
7. GPT-4o schreibt deutsche + englische Narration
8. Output-Ordner mit allen Assets, `video_prompts.md`, `narration.md`, `_meta.json`

Video-Generation (Kling 2.5 / 3.0 Omni / Seedance) passiert manuell per Copy-Paste.

## Setup

### Voraussetzungen

- Python 3.11+
- Windows (Linux/Mac auch möglich, `start.bat` ersetzen)
- AI-Auto API Key
- OpenAI API Key

### Erstinstallation

```bat
start.bat
```

Beim ersten Start legt das Script `.venv/` an, installiert Dependencies, kopiert `.env.example` nach `.env` (API Keys dort eintragen) und startet den Server.

### Signature Background

Lege dein vorhandenes `signature_background.png` nach `assets/signature_background.png`. Wird für Step 3 + Step 4 als Referenz verwendet.

## Nutzung

Nach `start.bat` öffnet sich automatisch http://127.0.0.1:8765

**Idea Generator** — Hint eingeben ("Legendary and Random"), 6 Vorschläge werden generiert, approven, "Run Pipeline on Approved" starten.

**Manual Fusion** — Pokémon A + B + optionaler Tone-Hint, einzelne Fusion starten.

**Active Pipelines** — Live-Status aller Jobs, Thumbnails der 5 Varianten, Regenerate-Button pro Variante, Link zur `video_prompts.md` und `narration.md`.

## Projektstruktur

```
fusion-auto/
├── backend/
│   ├── config.py           Pfade, API Keys, Settings
│   ├── prompts.py          ALLE Prompts (verbatim aus Guide)
│   ├── server.py           FastAPI Endpoints
│   ├── pipeline/runner.py  Orchestrator
│   └── clients/            AI-Auto, OpenAI, PokeAPI
├── dashboard/index.html    Single-Page Dashboard
├── assets/                 signature_background.png (manuell)
├── pokemon_refs/           Auto-cached PokeAPI PNGs
└── output/                 Pro Fusion ein Ordner
```
