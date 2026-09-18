from travel_adviser.tools.weather import get_weather


def test_get_weather_without_api_key_returns_graceful_error(monkeypatch):
    monkeypatch.setattr("travel_adviser.tools.weather.OPENWEATHER_API_KEY", "")
    result = get_weather("Tokyo")
    assert "error" in result
    assert result["forecast"] == []
