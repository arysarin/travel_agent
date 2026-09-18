"""Amadeus Flight Offers Search — self-serve backup to SerpAPI for flights.

SerpAPI's free tier is only 100 searches/month, easy to exhaust; Amadeus's
test environment is a separate free self-serve account with its own quota.
Requires exact IATA airport/city codes (unlike SerpAPI, which tolerates
looser input) — a request using a city name here will fail.
"""

import time

import requests

from ..config import AMADEUS_API_KEY, AMADEUS_API_SECRET, API_TIMEOUT_SECONDS

TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
FLIGHT_OFFERS_URL = "https://test.api.amadeus.com/v1/shopping/flight-offers"

_token_cache = {"access_token": None, "expires_at": 0.0}


def _get_access_token() -> str:
    """Returns a cached OAuth2 token, refreshing it if expired."""
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_API_KEY,
            "client_secret": AMADEUS_API_SECRET,
        },
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    # Refresh a little early rather than exactly at expiry.
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data["expires_in"] - 30
    return _token_cache["access_token"]


def search_flights_amadeus(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str = "",
) -> dict:
    """Searches flights via Amadeus. Same return shape as tools.flights.search_flights.

    Args:
        origin: Exact IATA airport/city code, e.g. "JFK".
        destination: Exact IATA airport/city code, e.g. "NRT".
        outbound_date: Departure date in YYYY-MM-DD format.
        return_date: Return date in YYYY-MM-DD format, or empty for one-way.
    """
    if not AMADEUS_API_KEY or not AMADEUS_API_SECRET:
        return {"error": "AMADEUS_API_KEY/AMADEUS_API_SECRET not configured", "flights": []}

    try:
        token = _get_access_token()
    except requests.RequestException as exc:
        return {"error": f"Amadeus auth failed: {exc}", "flights": []}

    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": outbound_date,
        "adults": 1,
        "max": 10,
    }
    if return_date:
        params["returnDate"] = return_date

    try:
        response = requests.get(
            FLIGHT_OFFERS_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"error": f"Amadeus flight search failed: {exc}", "flights": []}

    flights = [
        {
            "airline": (offer.get("validatingAirlineCodes") or ["unknown"])[0],
            "price": offer.get("price", {}).get("total"),
            "total_duration_minutes": None,
            "stops": sum(
                max(len(itin.get("segments", [])) - 1, 0)
                for itin in offer.get("itineraries", [])
            ),
        }
        for offer in data.get("data", [])
    ]
    return {"flights": flights, "source": "amadeus"}
