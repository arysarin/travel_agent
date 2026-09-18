from travel_adviser.tools.hotels import search_hotels


def test_search_hotels_without_api_key_returns_graceful_error(monkeypatch):
    monkeypatch.setattr("travel_adviser.tools.hotels.SERPAPI_API_KEY", "")
    result = search_hotels("Tokyo, Japan", "2026-11-01", "2026-11-05")
    assert "error" in result
    assert result["hotels"] == []
