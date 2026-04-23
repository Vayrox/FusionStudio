"""
PokeAPI-Client fuer Referenzbilder. Laedt official artwork herunter und cached.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import httpx

from backend.config import POKEAPI_BASE_URL, POKEMON_REFS_DIR


# Edge-Cases die die einfache Slug-Regel nicht abbildet.
_SPECIAL_SLUG_MAP = {
    "nidoranf": "nidoran-f",
    "nidoranm": "nidoran-m",
    "nidoran-female": "nidoran-f",
    "nidoran-male": "nidoran-m",
    "farfetchd": "farfetchd",
    "sirfetchd": "sirfetchd",
    "mimejr": "mime-jr",
    "typenull": "type-null",
    "jangmoo": "jangmo-o",
    "hakamoo": "hakamo-o",
    "kommoo": "kommo-o",
    "porygonz": "porygon-z",
    "mrmime": "mr-mime",
    "mrrime": "mr-rime",
    "tapukoko": "tapu-koko",
    "tapulele": "tapu-lele",
    "tapubulu": "tapu-bulu",
    "tapufini": "tapu-fini",
    "greattusk": "great-tusk",
    "screamtail": "scream-tail",
    "brutebonnet": "brute-bonnet",
    "fluttermane": "flutter-mane",
    "slitherwing": "slither-wing",
    "sandyshocks": "sandy-shocks",
    "ironthorns": "iron-thorns",
    "ironbundle": "iron-bundle",
    "ironhands": "iron-hands",
    "ironjugulis": "iron-jugulis",
    "ironmoth": "iron-moth",
    "ironvaliant": "iron-valiant",
    "roaringmoon": "roaring-moon",
    "ironleaves": "iron-leaves",
    "walkingwake": "walking-wake",
}


def pokemon_slug(name: str) -> str:
    """Normalisiert einen Pokemon-Namen in den PokeAPI-Slug.

    "Mr Mime"    -> "mr-mime"
    "Ho-Oh"      -> "ho-oh"
    "Nidoran F"  -> "nidoran-f"
    "Farfetch'd" -> "farfetchd"
    """
    # Unicode-Zeichen in ASCII zerlegen (entfernt Accents, aber auch ♀/♂).
    # Wir ersetzen Gender-Symbole explizit vorher.
    name = name.replace("♀", " f").replace("♂", " m")
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")

    # Apostrophe entfernen (Farfetch'd -> Farfetchd).
    name = name.replace("'", "")
    # Dots entfernen (Mr. Mime -> Mr Mime).
    name = name.replace(".", "")

    # Kleinschreibung
    lower = name.lower().strip()

    # Alles was nicht alphanumerisch ist -> Bindestrich
    slug = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")

    # Bekannte Edge-Cases (check ohne Bindestriche)
    key = slug.replace("-", "")
    if key in _SPECIAL_SLUG_MAP:
        return _SPECIAL_SLUG_MAP[key]

    return slug


def cached_path(slug: str) -> Path:
    return POKEMON_REFS_DIR / f"{slug}.png"


async def fetch_official_artwork(name: str) -> Path:
    """Laedt official-artwork fuer einen Pokemon-Namen, gibt lokalen Pfad zurueck.

    Cached - wenn die Datei schon existiert, wird sie nicht erneut geladen.
    """
    slug = pokemon_slug(name)
    target = cached_path(slug)
    if target.exists() and target.stat().st_size > 0:
        return target

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Pokemon-Endpoint fuer die Artwork-URL
        resp = await client.get(f"{POKEAPI_BASE_URL}/pokemon/{slug}")
        if resp.status_code == 404:
            raise ValueError(
                f"Pokemon '{name}' (slug '{slug}') wurde in der PokeAPI nicht gefunden."
            )
        resp.raise_for_status()
        data = resp.json()

        artwork_url = (
            data.get("sprites", {})
            .get("other", {})
            .get("official-artwork", {})
            .get("front_default")
        )
        if not artwork_url:
            # Fallback auf den normalen front_default
            artwork_url = data.get("sprites", {}).get("front_default")
        if not artwork_url:
            raise ValueError(f"Kein Artwork fuer '{name}' verfuegbar.")

        img_resp = await client.get(artwork_url)
        img_resp.raise_for_status()
        target.write_bytes(img_resp.content)

    return target
