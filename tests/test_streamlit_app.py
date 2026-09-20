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
