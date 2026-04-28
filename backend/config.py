"""
Zentrale Konfiguration. Pfade sind Konstanten, API-Keys/Models werden ueber
das globale `settings`-Objekt dynamisch aus der Umgebung gelesen und koennen
zur Laufzeit vom Dashboard aktualisiert werden (schreibt .env).
"""
from __future__ import annotations

import os
import re
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
ENV_FILE = PROJECT_ROOT / ".env"

# Cache fuer Step-2 Realistic-Single-Outputs: spart pro wiederholtem
# Pokemon einen kompletten AI-Auto-Roundtrip (~5min via 524-Fallback).
REALISTIC_CACHE_DIR = POKEMON_REFS_DIR / "realistic"

for _dir in (ASSETS_DIR, POKEMON_REFS_DIR, OUTPUT_DIR, STATE_DIR, REALISTIC_CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 8765

# ---------------------------------------------------------------------------
# Pipeline-Settings (statisch)
# ---------------------------------------------------------------------------

STEP4_VARIANTS = 3
SHOWCASE_VARIANTS = 4
DEFAULT_ASPECT_RATIO = "9:16"

MAX_PARALLEL_FUSIONS = 3
MAX_PARALLEL_AIAUTO_CALLS = 4

AIAUTO_REQUEST_TIMEOUT_S = 300.0
AIAUTO_POST_TIMEOUT_S = 100.0  # unter Cloudflare-524-Grenze (120s), dann Fallback via /generations
AIAUTO_POLL_INTERVAL_S = 5.0
AIAUTO_POLL_TIMEOUT_S = 900.0  # Nano Banana Pro kann lange brauchen
AIAUTO_VIDEO_POLL_TIMEOUT_S = 1800.0  # Seedance-2 Video-Gen kann 15+min brauchen
AIAUTO_LIST_MATCH_ATTEMPTS = 30
# Toleranz RUECKWAERTS vom submit_ts - nur Generations die hoechstens so
# viele Sekunden vor unserem POST angelegt wurden, gelten als Treffer.
# Bewusst eng, damit ALTE Generations aus frueheren Runs nicht
# faelschlich uebernommen werden. 15s reicht fuer Server-Clock-Skew.
AIAUTO_LIST_MATCH_TOLERANCE_S = 15.0

POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"


# ---------------------------------------------------------------------------
# Dynamische Settings (Keys + Model-Namen)
# ---------------------------------------------------------------------------

# Env laden (initial; wird bei settings.reload() erneut gerufen).
load_dotenv(ENV_FILE)

# Welche Keys vom Dashboard editierbar sind und ihre Defaults.
EDITABLE_SETTINGS: dict[str, str] = {
    "AIAUTO_API_KEY": "",
    "AIAUTO_BASE_URL": "https://api.ai-auto.io/api/saas",
    "AIAUTO_IMAGE_MODEL": "nano_banana_pro",
    "AIAUTO_IMAGE_RESOLUTION": "2k",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4o",
    "STEP4_DESIGN_MODE": "blend",
}

# Welche davon sind Secrets (im UI maskiert, nie im Klartext zurueckgegeben).
SECRET_KEYS = {"AIAUTO_API_KEY", "OPENAI_API_KEY"}


class Settings:
    """Lazy-Wrapper um os.environ. Liest immer zur Aufrufzeit."""

    @staticmethod
    def _get(name: str) -> str:
        val = os.getenv(name, EDITABLE_SETTINGS.get(name, ""))
        return val.strip() if isinstance(val, str) else val

    # Getters
    @property
    def aiauto_api_key(self) -> str:
        return self._get("AIAUTO_API_KEY")

    @property
    def aiauto_base_url(self) -> str:
        return self._get("AIAUTO_BASE_URL").rstrip("/")

    @property
    def aiauto_image_model(self) -> str:
        return self._get("AIAUTO_IMAGE_MODEL")

    @property
    def aiauto_image_resolution(self) -> str:
        return self._get("AIAUTO_IMAGE_RESOLUTION")

    @property
    def openai_api_key(self) -> str:
        return self._get("OPENAI_API_KEY")

    @property
    def openai_model(self) -> str:
        return self._get("OPENAI_MODEL")

    @property
    def step4_design_mode(self) -> str:
        """'blend' (default, behält erkennbare Features beider Originale)
        oder 'unique' (alter Stil, völlig neue Farb-/Feature-Wahl,
        nur Silhouette inheritance)."""
        v = (self._get("STEP4_DESIGN_MODE") or "blend").lower().strip()
        return v if v in ("blend", "unique") else "blend"

    # Laufzeit-Support

    def reload(self) -> None:
        """Laedt .env neu (override existing env vars)."""
        load_dotenv(ENV_FILE, override=True)

    def snapshot_public(self) -> dict[str, object]:
        """Gibt den aktuellen Stand fuer das Dashboard zurueck.

        Secrets werden NICHT im Klartext ausgeliefert - nur ein is-set-Flag
        und die letzten 4 Zeichen als Suffix.
        """
        out: dict[str, object] = {}
        for key in EDITABLE_SETTINGS:
            val = self._get(key)
            if key in SECRET_KEYS:
                out[key] = {
                    "set": bool(val),
                    "suffix": val[-4:] if val else "",
                }
            else:
                out[key] = val
        return out

    def update(self, updates: dict[str, str]) -> list[str]:
        """Schreibt updates in .env und aktualisiert os.environ.

        Leere Werte bei Secret-Keys werden ignoriert (damit man nicht
        versehentlich einen vorhandenen Key loescht, wenn man ein anderes
        Feld editiert). Nicht-Secret-Keys duerfen auf leer gesetzt werden,
        fallen dann auf den Default zurueck.

        Gibt die Liste der tatsaechlich geaenderten Keys zurueck.
        """
        changed: list[str] = []
        # Bestehende .env einlesen
        env_map = _parse_env_file(ENV_FILE)

        for key, raw in updates.items():
            if key not in EDITABLE_SETTINGS:
                continue
            val = (raw or "").strip()
            if not val and key in SECRET_KEYS:
                # Leer bei Secret -> ignorieren, nicht loeschen
                continue
            env_map[key] = val
            os.environ[key] = val
            changed.append(key)

        # Sicherstellen dass alle EDITABLE_SETTINGS in der .env existieren,
        # damit .env.example-Vollstaendigkeit lesbar bleibt.
        for key, default in EDITABLE_SETTINGS.items():
            env_map.setdefault(key, default)

        _write_env_file(ENV_FILE, env_map)
        return changed


settings = Settings()


# ---------------------------------------------------------------------------
# .env-File Parsing / Writing
# ---------------------------------------------------------------------------

_ENV_LINE_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$")


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # Trailing comments sauber abschneiden wenn Value nicht in Quotes
        if val and val[0] not in ("'", '"'):
            hash_idx = val.find(" #")
            if hash_idx >= 0:
                val = val[:hash_idx].rstrip()
        # Optional umschliessende Quotes entfernen
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


def _write_env_file(path: Path, env_map: dict[str, str]) -> None:
    lines: list[str] = []
    for key in EDITABLE_SETTINGS:
        val = env_map.get(key, EDITABLE_SETTINGS[key])
        lines.append(f"{key}={val}")
    # Zusaetzliche Keys (die nicht editable sind) behalten
    for key, val in env_map.items():
        if key in EDITABLE_SETTINGS:
            continue
        lines.append(f"{key}={val}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
