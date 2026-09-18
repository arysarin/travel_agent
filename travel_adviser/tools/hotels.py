"""Hotel search via SerpAPI's Google Hotels engine."""

import requests

from ..config import API_TIMEOUT_SECONDS, SERPAPI_API_KEY
from ..logging_utils import log_call

SERPAPI_URL = "https://serpapi.com/search"


@log_call("tool_call")
def search_hotels(
    location: str,
    check_in_date: str,
    check_out_date: str,
    max_price: float = 0,
) -> dict:
    """Search hotels in a location for a given date range.

    Args:
        location: City or area to search, e.g. "Tokyo, Japan".
        check_in_date: Check-in date in YYYY-MM-DD format.
        check_out_date: Check-out date in YYYY-MM-DD format.
        max_price: Optional nightly price ceiling in USD. Pass 0 for no cap.

    Returns:
        A dict with a "hotels" list of options (each with name, price per
        night, rating), or an "error" key if the search could not be
        completed so the caller can degrade gracefully instead of crashing.
    """
    if not SERPAPI_API_KEY:
        return {"error": "SERPAPI_API_KEY not configured", "hotels": []}

    params = {
        "engine": "google_hotels",
        "q": location,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "api_key": SERPAPI_API_KEY,
    }
    if max_price:
        params["max_price"] = max_price

    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"error": f"hotel search failed: {exc}", "hotels": []}

    properties = data.get("properties", [])
    hotels = [
        {
            "name": prop.get("name", "unknown"),
            "price_per_night": prop.get("rate_per_night", {}).get("extracted_lowest"),
            "rating": prop.get("overall_rating"),
        }
        for prop in properties
    ]
    return {"hotels": hotels}
