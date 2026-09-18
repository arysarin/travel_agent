"""Streamlit demo UI for Travel Adviser.

Runs the agent in-process via ADK's InMemoryRunner rather than spawning a
separate `adk api_server` — one process, one `streamlit run` command, no
extra moving parts. Trades away live token streaming for simplicity: each
request runs fully, then the whole conversation is rendered at once.
"""

import asyncio
import uuid

import streamlit as st
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from travel_adviser.agent import root_agent
from travel_adviser.config import (
    GEMINI_FALLBACK_MODEL,
    GROQ_API_KEY,
    MAX_BUDGET_ROUNDS,
    MAX_LLM_CALLS,
    MODEL_NAME,
    OPENROUTER_API_KEY,
)

APP_NAME = "travel_adviser"
USER_ID = "streamlit_user"

# Which pipeline stage each agent's output belongs under, for grouping.
STAGE_LABELS = {
    "destination_agent": "🌍 Destination",
    "itinerary_agent": "🗓️ Itinerary",
    "transportation_agent": "✈️ Flights",
    "accommodation_agent": "🏨 Hotel",
    "budget_agent": "💰 Budget",
    "weather_agent": "☀️ Weather & Safety",
    "final_merge_agent": "📋 Full Trip Plan",
}

EXAMPLE_REQUEST = (
    "Plan a 5-day trip to Kyoto, Japan under $2500, departing JFK on "
    "2026-11-10 and returning 2026-11-15."
)


@st.cache_resource
def get_runner() -> InMemoryRunner:
    return InMemoryRunner(agent=root_agent, app_name=APP_NAME)


async def run_trip_request(runner: InMemoryRunner, session_id: str, message: str):
    """Runs one full pipeline invocation and returns events grouped by agent."""
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    stages: dict[str, str] = {}
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
    ):
        if event.partial or not event.content or not event.content.parts:
            continue
        text = "".join(p.text for p in event.content.parts if p.text)
        if not text:
            continue
        stages[event.author] = stages.get(event.author, "") + text
    return stages


_fallback_rungs = []
if GEMINI_FALLBACK_MODEL:
    _fallback_rungs.append("Gemini")
if GROQ_API_KEY:
    _fallback_rungs.append("Groq")
if OPENROUTER_API_KEY:
    _fallback_rungs.append("OpenRouter")
_fallback_note = f" (+ {' → '.join(_fallback_rungs)} fallback)" if _fallback_rungs else ""

st.set_page_config(page_title="Travel Adviser", page_icon="🧳", layout="centered")
st.title("🧳 Travel Adviser")
st.caption(
    f"Multi-agent trip planner · model: {MODEL_NAME}{_fallback_note}"
    f" · budget revisions capped at {MAX_BUDGET_ROUNDS} rounds"
)

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "stages" not in st.session_state:
    st.session_state.stages = None
if "error" not in st.session_state:
    st.session_state.error = None

with st.form("trip_request_form"):
    request_text = st.text_area(
        "Describe the trip you want planned",
        value=EXAMPLE_REQUEST,
        height=100,
    )
    submitted = st.form_submit_button("Plan my trip", type="primary")

if submitted and request_text.strip():
    # A fresh id every submission, even a retry of the same text — the
    # deterministic hash-based id this used before collided with ADK's
    # create_session on a second click, which isn't idempotent and raises
    # instead of reusing the existing session.
    st.session_state.session_id = f"session-{uuid.uuid4()}"
    st.session_state.error = None
    runner = get_runner()
    with st.spinner(
        "Planning your trip — this runs several agents and can take a minute..."
    ):
        try:
            st.session_state.stages = asyncio.run(
                run_trip_request(runner, st.session_state.session_id, request_text)
            )
        except Exception as exc:  # noqa: BLE001 - surface any provider/config error to the UI
            st.session_state.stages = None
            st.session_state.error = str(exc)

if st.session_state.error:
    st.error(
        "The run failed — this is usually a provider quota/rate limit, not a "
        "bug in the plan itself. Try again shortly, or add GEMINI_FALLBACK_MODEL"
        "/GROQ_API_KEY/OPENROUTER_API_KEY in .env for more fallback rungs."
        f"\n\n```\n{st.session_state.error}\n```"
    )

if st.session_state.stages:
    final_text = st.session_state.stages.get("final_merge_agent")
    if final_text:
        st.markdown(final_text)
    else:
        st.warning(
            "The run didn't reach the final merge step — see the stage "
            "breakdown below for what did complete."
        )

    other_stages = {
        author: text
        for author, text in st.session_state.stages.items()
        if author != "final_merge_agent"
    }
    if other_stages:
        with st.expander("See each agent's individual output"):
            for author, text in other_stages.items():
                st.subheader(STAGE_LABELS.get(author, author))
                st.markdown(text)
