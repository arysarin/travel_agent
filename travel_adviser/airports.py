import re
from functools import lru_cache

import airportsdata

_EXCLUDED_NAME_PARTS = (
    "heliport", "seaplane", "airstrip", "airfield", "air base", "air force",
    "military", "railway", "bus station", "ferry",
)
DEFAULT_AIRPORT_CODE = "JFK"


@lru_cache(maxsize=1)
def airport_options() -> tuple[dict[str, str], ...]:
    """Search-friendly labels like 'New Delhi (DEL) — Indira Gandhi International Airport, IN'; city and code lead so they survive truncation."""
    options = {}
    for code, info in airportsdata.load("IATA").items():
        name = info["name"]
        if not code or any(part in name.lower() for part in _EXCLUDED_NAME_PARTS):
            continue
        city = info["city"] or name
        options[code] = f"{city} ({code}) — {name}, {info['country']}"
    ordered = sorted(options.items(), key=lambda kv: kv[1].lower())
    return tuple({"code": code, "label": label} for code, label in ordered)


def airport_labels() -> list[str]:
    return [o["label"] for o in airport_options()]


def code_from_label(label: str) -> str:
    return re.search(r"\(([A-Z0-9]{3})\) — ", label).group(1)


def default_label() -> str:
    return next(o["label"] for o in airport_options() if o["code"] == DEFAULT_AIRPORT_CODE)
