from travel_adviser.tools import flights


def test_search_flights_without_any_keys_returns_graceful_error(monkeypatch):
    monkeypatch.setattr(flights, "SERPAPI_API_KEY", "")
    monkeypatch.setattr("travel_adviser.tools.amadeus_client.AMADEUS_API_KEY", "")
    result = flights.search_flights("JFK", "NRT", "2026-11-01")
    assert "error" in result
    assert result["flights"] == []


def test_search_flights_falls_back_to_amadeus_when_serpapi_unavailable(monkeypatch):
    monkeypatch.setattr(flights, "SERPAPI_API_KEY", "")
    monkeypatch.setattr(
        flights,
        "search_flights_amadeus",
        lambda *a, **k: {"flights": [{"airline": "Test Air", "price": 500}], "source": "amadeus"},
    )
    result = flights.search_flights("JFK", "NRT", "2026-11-01")
    assert "error" not in result
    assert result["source"] == "amadeus"
    assert result["flights"][0]["airline"] == "Test Air"


def test_search_flights_does_not_call_amadeus_when_serpapi_succeeds(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Amadeus should not be called when SerpAPI succeeds")

    monkeypatch.setattr(
        flights,
        "_search_flights_serpapi",
        lambda *a, **k: {"flights": [{"airline": "SerpAPI Air", "price": 400}], "source": "serpapi"},
    )
    monkeypatch.setattr(flights, "search_flights_amadeus", fail_if_called)
    result = flights.search_flights("JFK", "NRT", "2026-11-01")
    assert result["source"] == "serpapi"
