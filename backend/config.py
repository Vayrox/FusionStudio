"""
Zentrale Konfiguration. Pfade, API Keys, Settings.
Alle Pfade sind absolute und relativ zum Projekt-Root resolved.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
POKEMON_REFS_DIR = PROJECT_ROOT / "pokemon_refs"
OUTPUT_DIR = PROJECT_ROOT / "output"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
STATE_DIR = PROJECT_ROOT / ".state"

SIGNATURE_BACKGROUND_PATH = ASSETS_DIR / "signature_background.png"
STATE_FILE = STATE_DIR / "jobs.json"

for _dir in (ASSETS_DIR, POKEMON_REFS_DIR, OUTPUT_DIR, STATE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Env laden
# ---------------------------------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env")

AIAUTO_API_KEY = os.getenv("AIAUTO_API_KEY", "")
AIAUTO_BASE_URL = os.getenv("AIAUTO_BASE_URL", "https://api.ai-auto.com/v1").rstrip("/")
AIAUTO_MODEL = os.getenv("AIAUTO_MODEL", "nano-banana-pro-4k")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 8765

# ---------------------------------------------------------------------------
# Pipeline-Settings
# ---------------------------------------------------------------------------

STEP4_VARIANTS = 5
DEFAULT_ASPECT_RATIO = "9:16"
IMAGE_RESOLUTION = "4K"

# Max gleichzeitig laufende Fusion-Jobs (voneinander unabhaengig)
MAX_PARALLEL_FUSIONS = 3

# Globale Begrenzung fuer gleichzeitige AI-Auto-Calls.
# AI-Auto erlaubt laut User bis zu 4 parallele Generations.
MAX_PARALLEL_AIAUTO_CALLS = 4

# HTTP-Timeouts und Retries fuer AI-Auto
AIAUTO_REQUEST_TIMEOUT_S = 300.0
AIAUTO_POLL_INTERVAL_S = 5.0
AIAUTO_POLL_TIMEOUT_S = 600.0

# PokeAPI
POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
