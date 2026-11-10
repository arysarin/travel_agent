"""Headless render checks for the Streamlit UI — no LLM calls, no quota."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")

FAKE_STAGES = {
    "destination_agent": ["Destination confirmed: Kyoto, Japan."],
    "itinerary_agent": ["Round 1 itinerary", "Round 2 revised itinerary"],
    "transportation_agent": ["Flights: JFK-KIX $1200"],
    "accommodation_agent": ["Hotel: Kiori $126/night"],
    "budget_agent": ["Over budget by $300", "Within budget"],
    "weather_agent": ["Mild, 14-20C"],
    "final_merge_agent": ["# Kyoto trip plan"],
}


def _app() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=30)


def test_results_view_renders_tabs_and_metrics():
    at = _app()
    at.session_state["stages"] = FAKE_STAGES
    at.session_state["elapsed"] = 42.0
    at.run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels.index("📋 Full Trip Plan") < labels.index("🌍 Destination")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Stages completed"] == "7 / 7"
    assert metrics["Budget revision rounds"] == "1"


def test_error_state_renders_message():
    at = _app()
    at.session_state["error"] = "429 RESOURCE_EXHAUSTED"
    at.run()
    assert not at.exception
    assert len(at.error) == 1


def test_origin_is_searchable_airport_dropdown():
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    box = next(s for s in at.selectbox if s.key == "origin_airport")
    assert "(JFK)" in box.value
    assert len(box.options) > 1000


POOR_WEATHER = {
    "location": "Goa, India",
    "based_on_city": "Panjim, India",
    "requested": {"start": "2027-07-10", "end": "2027-07-14", "score": 48, "rating": "poor",
                  "expected_rainy_days": 4.2, "avg_temp_c": 26.0, "avg_high_c": 29.0},
    "weather_is_good": False,
    "suggested_windows": [
        {"start": "2027-12-05", "end": "2027-12-09", "score": 95, "rating": "good",
         "expected_rainy_days": 0.1, "avg_temp_c": 27.0, "avg_high_c": 31.0},
    ],
    "basis": "average of the last 5 years of weather for these calendar days (Open-Meteo); a seasonal estimate, not a forecast",
}


def _configure_email(monkeypatch):
    from travel_adviser import emailer

    sent = []

    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, message):
            sent.append(message)

    emailer._sent_at.clear()
    monkeypatch.setattr(emailer, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(emailer, "SMTP_PASSWORD", "pw")
    monkeypatch.setattr(emailer, "SMTP_FROM", "sender@example.com")
    monkeypatch.setattr(emailer.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(emailer, "_write_event", lambda record: None)
    return sent


def test_poor_weather_shows_better_dates_card():
    at = _app()
    at.session_state["weather_check"] = POOR_WEATHER
    at.run()
    assert not at.exception
    assert any("poor" in w.value for w in at.warning)
    assert any("2027-12-05" in m.value for m in at.markdown)


def test_email_inputs_disabled_when_smtp_not_configured(monkeypatch):
    from travel_adviser import emailer

    monkeypatch.setattr(emailer, "SMTP_PASSWORD", "")
    at = _app().run()
    assert at.text_input(key="guided_email").disabled
    assert at.text_input(key="free_email").disabled


def test_invalid_email_blocks_the_run(monkeypatch):
    _configure_email(monkeypatch)
    at = _app().run()
    at.text_input(key="guided_email").set_value("not-an-email")
    next(b for b in at.button if b.label == "Plan my trip").click()
    at.run()
    assert any("email" in w.value.lower() for w in at.warning)
    assert at.session_state["stages"] is None


def test_resend_button_emails_plan_with_better_dates(monkeypatch):
    sent = _configure_email(monkeypatch)
    at = _app()
    at.session_state["stages"] = FAKE_STAGES
    at.session_state["weather_check"] = POOR_WEATHER
    at.session_state["trip"] = {"destination": "Goa, India"}
    at.run()
    at.text_input(key="resend_email").set_value("traveler@example.com")
    next(b for b in at.button if b.label == "Send email").click()
    at.run()
    assert not at.exception
    assert any("emailed to traveler@example.com" in s.value for s in at.success)
    body = sent[0].get_body(preferencelist=("plain",)).get_content()
    assert "# Kyoto trip plan" in body and "Better travel dates" in body and "2027-12-05" in body
    assert sent[0]["Subject"] == "Your trip plan: Goa, India"


def test_guided_submit_checks_weather_and_auto_emails(monkeypatch):
    from datetime import date, timedelta

    from tests.test_weather_window import _fake_history, _patch

    sent = _configure_email(monkeypatch)
    _patch(monkeypatch, _fake_history(rainy_months={6, 7, 8}))
    monkeypatch.setattr("asyncio.run", lambda coro: (coro.close(), FAKE_STAGES)[1])

    today = date.today()
    july = date(today.year, 7, 10)
    if july <= today + timedelta(days=30):
        july = date(today.year + 1, 7, 10)

    at = _app().run()
    at.text_input(key="destination_input").set_value("Goa, India")
    at.date_input(key="travel_dates").set_value((july, july + timedelta(days=4)))
    at.text_input(key="guided_email").set_value("traveler@example.com")
    next(b for b in at.button if b.label == "Plan my trip").click()
    at.run()

    assert not at.exception, at.exception
    assert any("typically" in w.value and "Better dates" not in w.value for w in at.warning)
    assert any("Better dates to consider" in m.value for m in at.markdown)
    assert any("emailed to traveler@example.com" in s.value for s in at.success)
    body = sent[0].get_body(preferencelist=("plain",)).get_content()
    assert "Better travel dates" in body
