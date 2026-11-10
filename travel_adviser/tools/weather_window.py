"""Finds better travel dates when the requested window has poor typical weather.

Uses Open-Meteo (free, no API key): its geocoder to locate the destination
and its historical archive to build a day-of-year climatology from the last
five full years. That makes it usable for trips months away, which the free
OpenWeatherMap forecast (5 days) can't cover. Results are averages of past
weather, not a forecast, and are labelled that way.
"""

import unicodedata
from datetime import date, timedelta

import requests

from ..config import API_TIMEOUT_SECONDS
from ..logging_utils import log_call

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HISTORY_YEARS = 5
RAIN_DAY_MM = 2.5
IDEAL_TEMP_C = (15.0, 27.0)
GOOD_SCORE = 70
MIN_IMPROVEMENT = 8
SEARCH_BACK_DAYS = 120
SEARCH_FORWARD_DAYS = 150
STEP_DAYS = 7
MIN_SEPARATION_DAYS = 14
MAX_SUGGESTIONS = 3


_REGION_ALIASES = {  # regions the geocoder doesn't know -> a representative town
    "goa": "Panjim",
    "ladakh": "Leh",
    "sikkim": "Gangtok",
    "kashmir": "Srinagar",
    "kerala": "Kochi",
}


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).strip()


def _geocode(location: str) -> dict | None:
    """Exact-name match only: the geocoder fuzzy-matches (e.g. 'Goa' -> Genoa, Italy),
    and weather advice for the wrong city is worse than no advice."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if not parts:
        return None
    name = _REGION_ALIASES.get(_norm(parts[0]), parts[0])
    response = requests.get(
        GEOCODE_URL,
        params={"name": name, "count": 20, "language": "en"},
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    matches = [r for r in response.json().get("results") or [] if _norm(r.get("name", "")) == _norm(name)]
    hints = {_norm(p) for p in parts[1:]}
    if hints:
        matches = [
            r for r in matches
            if hints & {_norm(str(r.get(k) or "")) for k in ("country", "country_code", "admin1")}
        ]
    return max(matches, key=lambda r: r.get("population") or 0) if matches else None


def _climatology(latitude: float, longitude: float) -> dict[tuple[int, int], list[tuple[float, float, float]]]:
    last_year = date.today().year - 1
    response = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": f"{last_year - HISTORY_YEARS + 1}-01-01",
            "end_date": f"{last_year}-12-31",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=max(API_TIMEOUT_SECONDS, 30),
    )
    response.raise_for_status()
    daily = response.json()["daily"]
    by_day: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    for day, tmax, tmin, rain in zip(
        daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"], daily["precipitation_sum"]
    ):
        if tmax is None or tmin is None or rain is None:
            continue
        d = date.fromisoformat(day)
        by_day.setdefault((d.month, d.day), []).append((tmax, tmin, rain))
    return by_day


def _window_stats(by_day, start: date, days: int) -> dict | None:
    rain_probs, temps, maxes = [], [], []
    for offset in range(days):
        d = start + timedelta(days=offset)
        samples = by_day.get((d.month, d.day))
        if not samples:
            continue
        rain_probs.append(sum(1 for _, _, r in samples if r >= RAIN_DAY_MM) / len(samples))
        temps.append(sum((hi + lo) / 2 for hi, lo, _ in samples) / len(samples))
        maxes.append(sum(hi for hi, _, _ in samples) / len(samples))
    if not temps:
        return None
    rain_frac = sum(rain_probs) / len(rain_probs)
    avg_temp = sum(temps) / len(temps)
    low, high = IDEAL_TEMP_C
    degrees_off = max(0.0, low - avg_temp, avg_temp - high)
    rain_penalty = min(1.0, rain_frac / 0.5) * 50
    temp_penalty = min(45.0, degrees_off * 3)
    score = max(0, round(100 - rain_penalty - temp_penalty))
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(days=days - 1)).isoformat(),
        "score": score,
        "rating": "good" if score >= GOOD_SCORE else "fair" if score >= 50 else "poor",
        "expected_rainy_days": round(rain_frac * days, 1),
        "avg_temp_c": round(avg_temp, 1),
        "avg_high_c": round(sum(maxes) / len(maxes), 1),
    }


@log_call("tool_call")
def suggest_better_dates(location: str, start_date: str, end_date: str = "") -> dict:
    """Checks typical weather for the trip dates and suggests better dates if it is poor.

    Based on five years of historical weather for the same calendar days
    (rain frequency and temperature), so it works for trips months away.
    It is a seasonal estimate, not a forecast.

    Args:
        location: Destination, e.g. "Kyoto, Japan" or "Goa, India".
        start_date: Trip start in YYYY-MM-DD format.
        end_date: Trip end in YYYY-MM-DD format. Optional; defaults to
            a 5-day window for one-way trips.

    Returns:
        A dict with the requested window's weather rating, whether it is
        good, and up to three better alternative windows of the same length
        (empty if the requested dates are already good or nothing is
        clearly better). Contains an "error" key if the lookup failed.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date) if end_date else start + timedelta(days=4)
    except ValueError:
        return {"error": "dates must be in YYYY-MM-DD format"}
    days = max(1, min((end - start).days + 1, 21))

    try:
        place = _geocode(location)
        if not place:
            return {"error": f"could not locate '{location}'"}
        by_day = _climatology(place["latitude"], place["longitude"])
    except (requests.RequestException, KeyError, ValueError) as exc:
        return {"error": f"weather history lookup failed: {exc}"}

    requested = _window_stats(by_day, start, days)
    if requested is None:
        return {"error": "no historical weather data for those dates"}

    result = {
        "location": location,
        "based_on_city": ", ".join(p for p in (place.get("name"), place.get("country")) if p),
        "requested": requested,
        "weather_is_good": requested["score"] >= GOOD_SCORE,
        "suggested_windows": [],
        "basis": f"average of the last {HISTORY_YEARS} years of weather for these calendar days (Open-Meteo); a seasonal estimate, not a forecast",
    }
    if result["weather_is_good"]:
        return result

    earliest = max(date.today() + timedelta(days=7), start - timedelta(days=SEARCH_BACK_DAYS))
    candidates = []
    cursor = earliest
    while cursor <= start + timedelta(days=SEARCH_FORWARD_DAYS):
        if cursor != start:
            stats = _window_stats(by_day, cursor, days)
            if stats and stats["score"] >= requested["score"] + MIN_IMPROVEMENT:
                candidates.append(stats)
        cursor += timedelta(days=STEP_DAYS)

    candidates.sort(key=lambda s: (-s["score"], abs((date.fromisoformat(s["start"]) - start).days)))
    chosen: list[dict] = []
    for stats in candidates:
        s = date.fromisoformat(stats["start"])
        if all(abs((s - date.fromisoformat(c["start"])).days) >= MIN_SEPARATION_DAYS for c in chosen):
            chosen.append(stats)
        if len(chosen) == MAX_SUGGESTIONS:
            break
    result["suggested_windows"] = chosen
    return result


def format_suggestions_markdown(check: dict) -> str:
    """Markdown 'Better travel dates' section, or '' when there's nothing to suggest."""
    if not check or "error" in check or check.get("weather_is_good") or not check.get("suggested_windows"):
        return ""
    q = check["requested"]
    lines = [
        "## Better travel dates",
        "",
        f"Typical weather for {q['start']} to {q['end']} is **{q['rating']}** "
        f"(about {q['expected_rainy_days']} rainy days, {q['avg_temp_c']}°C average). "
        "These alternatives are seasonal averages from past years, not a forecast, "
        "and flight and hotel prices were not re-checked for them.",
        "",
    ]
    for w in check["suggested_windows"]:
        lines.append(
            f"- **{w['start']} to {w['end']}** — {w['rating']}, "
            f"about {w['expected_rainy_days']} rainy days, {w['avg_temp_c']}°C average"
        )
    return "\n".join(lines)
