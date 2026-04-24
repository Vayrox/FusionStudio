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


# In-Memory-Cache fuer lokalisierte Namen - spart PokeAPI-Calls bei
# wiederholtem Zugriff innerhalb einer Server-Session.
_LOCALIZED_NAMES_CACHE: dict[str, dict[str, str]] = {}


async def get_localized_names(name: str) -> dict[str, str]:
    """Holt alle Sprachvarianten des Pokemon-Namens von PokeAPI.

    Rueckgabe: dict {lang_code: localized_name}, z.B.
    {"en": "Charizard", "de": "Glurak", "fr": "Dracaufeu", ...}.
    Falls PokeAPI keine species liefert (selten), wird der Input
    als Fallback sowohl fuer 'en' als auch 'de' genommen.
    """
    slug = pokemon_slug(name)
    if slug in _LOCALIZED_NAMES_CACHE:
        return _LOCALIZED_NAMES_CACHE[slug]

    out: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{POKEAPI_BASE_URL}/pokemon-species/{slug}")
            if resp.status_code == 200:
                species = resp.json()
                for entry in species.get("names") or []:
                    lang = (entry.get("language") or {}).get("name")
                    nm = entry.get("name")
                    if lang and nm:
                        out[lang] = nm
    except Exception:  # noqa: BLE001
        pass

    out.setdefault("en", name)
    out.setdefault("de", out["en"])
    _LOCALIZED_NAMES_CACHE[slug] = out
    return out


async def _fetch_pokemon_data(client: httpx.AsyncClient, slug: str) -> dict | None:
    """GET /pokemon/{slug} oder None bei 404."""
    resp = await client.get(f"{POKEAPI_BASE_URL}/pokemon/{slug}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def _resolve_via_species(
    client: httpx.AsyncClient, slug: str
) -> dict | None:
    """Bei Form-only-Pokemon (Mimikyu, Wishiwashi, Minior, Urshifu, ...) gibt
    es keinen /pokemon/{slug}-Eintrag - nur /pokemon-species/{slug} mit den
    Varieties. Holt die default variety und laedt deren pokemon-Eintrag."""
    resp = await client.get(f"{POKEAPI_BASE_URL}/pokemon-species/{slug}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    species = resp.json()
    default_name: str | None = None
    for v in species.get("varieties", []) or []:
        pokemon = v.get("pokemon") or {}
        if v.get("is_default") and pokemon.get("name"):
            default_name = pokemon["name"]
            break
    if not default_name:
        # Fallback: erste variety
        varieties = species.get("varieties") or []
        if varieties:
            default_name = (varieties[0].get("pokemon") or {}).get("name")
    if not default_name:
        return None
    return await _fetch_pokemon_data(client, default_name)


def _extract_artwork_url(data: dict) -> str | None:
    url = (
        data.get("sprites", {})
        .get("other", {})
        .get("official-artwork", {})
        .get("front_default")
    )
    if url:
        return url
    return data.get("sprites", {}).get("front_default")


async def fetch_official_artwork(name: str) -> Path:
    """Laedt official-artwork fuer einen Pokemon-Namen, gibt lokalen Pfad zurueck.

    Cached - wenn die Datei schon existiert, wird sie nicht erneut geladen.
    """
    slug = pokemon_slug(name)
    target = cached_path(slug)
    if target.exists() and target.stat().st_size > 0:
        return target

    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await _fetch_pokemon_data(client, slug)
        if data is None:
            # Form-only oder Species-only Pokemon -> via species aufloesen
            data = await _resolve_via_species(client, slug)
        if data is None:
            raise ValueError(
                f"Pokemon '{name}' (slug '{slug}') wurde in der PokeAPI nicht gefunden."
            )

        artwork_url = _extract_artwork_url(data)
        if not artwork_url:
            raise ValueError(f"Kein Artwork fuer '{name}' verfuegbar.")

        img_resp = await client.get(artwork_url)
        img_resp.raise_for_status()
        target.write_bytes(img_resp.content)

    return target
