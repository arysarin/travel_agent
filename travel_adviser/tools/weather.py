"""Weather lookup via OpenWeatherMap's free-tier forecast endpoint.

The free tier only exposes a 5-day/3-hour forecast (no long-range forecast),
so dates beyond 5 days out cannot get a real forecast and are reported as
such rather than guessed at.
"""

import requests

from ..config import API_TIMEOUT_SECONDS, OPENWEATHER_API_KEY
from ..logging_utils import log_call

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


@log_call("tool_call")
def get_weather(location: str, date: str = "") -> dict:
    """Get a weather forecast summary for a location.

    Args:
        location: City name, e.g. "Tokyo" or "Kyoto,JP".
        date: Optional date in YYYY-MM-DD format. Only dates within the
            next 5 days can be forecast on the free API tier; anything
            further out returns a note instead of fabricated data.

    Returns:
        A dict with forecast summary fields, or an "error"/"note" key if
        no real forecast could be produced, so the caller can degrade
        gracefully instead of crashing.
    """
    if not OPENWEATHER_API_KEY:
        return {"error": "OPENWEATHER_API_KEY not configured", "forecast": []}

    params = {
        "q": location,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
    }

    try:
        response = requests.get(FORECAST_URL, params=params, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"error": f"weather lookup failed: {exc}", "forecast": []}

    entries = data.get("list", [])
    if date:
        entries = [e for e in entries if e.get("dt_txt", "").startswith(date)]
        if not entries:
            return {
                "note": f"{date} is outside the 5-day free-tier forecast window for {location}",
                "forecast": [],
            }

    forecast = [
        {
            "datetime": e.get("dt_txt"),
            "temp_c": e.get("main", {}).get("temp"),
            "conditions": (e.get("weather") or [{}])[0].get("description"),
        }
        for e in entries
    ]
    return {"forecast": forecast}
