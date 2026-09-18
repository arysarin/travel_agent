from travel_adviser.tools import amadeus_client


def test_search_flights_amadeus_without_keys_returns_graceful_error(monkeypatch):
    monkeypatch.setattr(amadeus_client, "AMADEUS_API_KEY", "")
    monkeypatch.setattr(amadeus_client, "AMADEUS_API_SECRET", "")
    result = amadeus_client.search_flights_amadeus("JFK", "NRT", "2026-11-01")
    assert "error" in result
    assert result["flights"] == []
