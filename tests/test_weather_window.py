from datetime import date, timedelta

from travel_adviser.tools import weather_window as ww


def _fake_history(rainy_months: set[int], temp: float = 22.0):
    """Five years of daily data: heavy rain in `rainy_months`, dry otherwise."""
    daily = {"time": [], "temperature_2m_max": [], "temperature_2m_min": [], "precipitation_sum": []}
    last_year = date.today().year - 1
    day = date(last_year - ww.HISTORY_YEARS + 1, 1, 1)
    while day <= date(last_year, 12, 31):
        daily["time"].append(day.isoformat())
        daily["temperature_2m_max"].append(temp + 4)
        daily["temperature_2m_min"].append(temp - 4)
        daily["precipitation_sum"].append(12.0 if day.month in rainy_months else 0.0)
        day += timedelta(days=1)
    return {"daily": daily}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


GOA = {"name": "Panjim", "country": "India", "country_code": "IN", "admin1": "Goa", "latitude": 15.5, "longitude": 73.8, "population": 5}


def _patch(monkeypatch, history, geocode_results=None):
    geocode_results = geocode_results if geocode_results is not None else [GOA]

    def fake_get(url, params=None, timeout=None):
        return _Resp({"results": geocode_results} if url == ww.GEOCODE_URL else history)

    monkeypatch.setattr(ww.requests, "get", fake_get)


def _future(month: int) -> date:
    today = date.today()
    d = date(today.year, month, 10)
    return d if d > today + timedelta(days=30) else date(today.year + 1, month, 10)


def test_rainy_dates_get_better_suggestions(monkeypatch):
    _patch(monkeypatch, _fake_history(rainy_months={6, 7, 8}))
    start = _future(7)
    result = ww.suggest_better_dates("Goa, India", start.isoformat(), (start + timedelta(days=4)).isoformat())
    assert result["weather_is_good"] is False
    assert result["requested"]["rating"] != "good"
    windows = result["suggested_windows"]
    assert 1 <= len(windows) <= ww.MAX_SUGGESTIONS
    for w in windows:
        assert w["score"] >= result["requested"]["score"] + ww.MIN_IMPROVEMENT
        assert date.fromisoformat(w["start"]) > date.today()
    assert "Better travel dates" in ww.format_suggestions_markdown(result)


def test_good_weather_returns_no_suggestions(monkeypatch):
    _patch(monkeypatch, _fake_history(rainy_months={6, 7, 8}))
    start = _future(1)
    result = ww.suggest_better_dates("Goa, India", start.isoformat(), (start + timedelta(days=4)).isoformat())
    assert result["weather_is_good"] is True
    assert result["suggested_windows"] == []
    assert ww.format_suggestions_markdown(result) == ""


def test_unknown_location_is_an_error_not_a_guess(monkeypatch):
    genoa = {"name": "Genoa", "country": "Italy", "country_code": "IT", "admin1": "Liguria", "latitude": 44.4, "longitude": 8.9}
    _patch(monkeypatch, _fake_history(set()), geocode_results=[genoa])
    result = ww.suggest_better_dates("Goa, India", "2027-01-10", "2027-01-14")
    assert "could not locate" in result["error"]


def test_bad_dates_and_network_errors_degrade_gracefully(monkeypatch):
    assert "YYYY-MM-DD" in ww.suggest_better_dates("Goa, India", "next week")["error"]

    def boom(*a, **k):
        raise ww.requests.ConnectionError("offline")

    monkeypatch.setattr(ww.requests, "get", boom)
    assert "lookup failed" in ww.suggest_better_dates("Goa, India", "2027-01-10", "2027-01-14")["error"]


def test_geocoder_prefers_country_match_and_population(monkeypatch):
    results = [
        {"name": "Jaipur", "country": "Bangladesh", "country_code": "BD", "admin1": "Chittagong", "population": None},
        {"name": "Jaipur", "country": "India", "country_code": "IN", "admin1": "Rajasthan", "population": 3_000_000},
    ]
    monkeypatch.setattr(ww.requests, "get", lambda *a, **k: _Resp({"results": results}))
    assert ww._geocode("Jaipur, India")["country"] == "India"


def test_region_alias_used_when_geocoder_lacks_region(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["name"] = params["name"]
        return _Resp({"results": [{"name": "Panjim", "country": "India", "country_code": "IN", "admin1": "Goa", "population": 70000}]})

    monkeypatch.setattr(ww.requests, "get", fake_get)
    assert ww._geocode("Goa, India")["name"] == "Panjim"
    assert seen["name"] == "Panjim"
