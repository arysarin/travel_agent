"""Flight search via SerpAPI's Google Flights engine, with Amadeus backup.

SerpAPI's free tier is only 100 searches/month. If it's unavailable
(missing key, timeout, or upstream error), this falls back to Amadeus
(tools/amadeus_client.py) when AMADEUS_API_KEY/SECRET are configured.
"""

import requests

from ..config import API_TIMEOUT_SECONDS, SERPAPI_API_KEY
from ..logging_utils import log_call
from .amadeus_client import search_flights_amadeus

SERPAPI_URL = "https://serpapi.com/search"


def _search_flights_serpapi(
    origin: str, destination: str, outbound_date: str, return_date: str
) -> dict:
    if not SERPAPI_API_KEY:
        return {"error": "SERPAPI_API_KEY not configured", "flights": []}

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "type": "1" if return_date else "2",
        "api_key": SERPAPI_API_KEY,
    }
    if return_date:
        params["return_date"] = return_date

    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"error": f"flight search failed: {exc}", "flights": []}

    options = data.get("best_flights", []) + data.get("other_flights", [])
    flights = [
        {
            "airline": opt.get("flights", [{}])[0].get("airline", "unknown"),
            "price": opt.get("price"),
            "total_duration_minutes": opt.get("total_duration"),
            "stops": max(len(opt.get("flights", [])) - 1, 0),
        }
        for opt in options
    ]
    return {"flights": flights, "source": "serpapi"}


@log_call("tool_call")
def search_flights(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str = "",
) -> dict:
    """Search round-trip or one-way flights between two airports.

    Args:
        origin: Departure airport IATA code, e.g. "JFK". Use the exact
            3-letter code, not a city name — required for the Amadeus
            backup to work if SerpAPI is unavailable.
        destination: Arrival airport IATA code, e.g. "NRT".
        outbound_date: Departure date in YYYY-MM-DD format.
        return_date: Return date in YYYY-MM-DD format. Leave empty for
            a one-way search.

    Returns:
        A dict with a "flights" list of options (each with airline, price,
        duration, stops) and which "source" answered it, or an "error" key
        if neither provider could complete the search, so the caller can
        degrade gracefully instead of crashing.
    """
    result = _search_flights_serpapi(origin, destination, outbound_date, return_date)
    if "error" not in result:
        return result

    fallback = search_flights_amadeus(origin, destination, outbound_date, return_date)
    if "error" not in fallback:
        return fallback

    # Both failed — surface SerpAPI's error since it's the primary source.
    return result
