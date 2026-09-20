"""Streamlit demo UI for Travel Adviser.

Runs the agent in-process via ADK's InMemoryRunner rather than spawning a
separate `adk api_server` — one process, one `streamlit run` command, no
extra moving parts. Each request runs the whole pipeline; progress is shown
live per stage as each agent finishes, and the results are rendered once
the run completes.
"""

import asyncio
import time
import uuid
from datetime import date, timedelta

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

# Pipeline order (matches agent.py) — also the order stages are displayed.
STAGE_LABELS = {
    "destination_agent": "🌍 Destination",
    "itinerary_agent": "🗓️ Itinerary",
    "transportation_agent": "✈️ Flights",
    "accommodation_agent": "🏨 Hotel",
    "budget_agent": "💰 Budget",
    "weather_agent": "☀️ Weather & Safety",
    "final_merge_agent": "📋 Full Trip Plan",
}
INTERESTS = [
    "Culture & history",
    "Food",
    "Adventure & outdoors",
    "Beaches",
    "Nightlife",
    "Shopping",
    "Relaxation",
    "Nature & wildlife",
]

EXAMPLE_REQUEST = (
    "Plan a 5-day trip to Kyoto, Japan under $2500, departing JFK on "
    "2026-11-10 and returning 2026-11-15."
)


@st.cache_resource
def get_runner() -> InMemoryRunner:
    return InMemoryRunner(agent=root_agent, app_name=APP_NAME)


async def run_trip_request(runner, session_id, message, on_stage):
    """Runs one full pipeline invocation; returns {agent: [outputs, ...]}.

    An agent can speak more than once (the budget loop revises itinerary,
    flights, and hotel across rounds), so outputs are kept as a list, oldest
    first, rather than concatenated.
    """
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    stages: dict[str, list[str]] = {}
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
    ):
        if event.partial or not event.content or not event.content.parts:
            continue
        text = "".join(p.text for p in event.content.parts if p.text)
        if not text or event.author not in STAGE_LABELS:
            continue
        stages.setdefault(event.author, []).append(text)
        on_stage(event.author, len(stages[event.author]))
    return stages


def build_prompt(destination, origin, start, end, one_way, budget, interests):
    """Turns the guided-form fields into the natural-language request."""
    parts = []
    if destination:
        parts.append(f"Plan a trip to {destination}")
    else:
        parts.append("Surprise me with a destination and plan a trip")
    if one_way:
        parts.append(f"a one-way journey departing {origin} on {start}")
    else:
        days = (end - start).days + 1
        parts.append(f"{days} days, departing {origin} on {start} and returning {end}")
    parts.append(f"under ${budget:,} total")
    prompt = ", ".join(parts) + "."
    if interests:
        prompt += f" Interests: {', '.join(i.lower() for i in interests)}."
    return prompt


def fallback_chain() -> list[str]:
    chain = [MODEL_NAME]
    if GEMINI_FALLBACK_MODEL:
        chain.append(GEMINI_FALLBACK_MODEL)
    if GROQ_API_KEY:
        chain.append("Groq")
    if OPENROUTER_API_KEY:
        chain.append("OpenRouter")
    return chain


def execute(request_text: str) -> None:
    """Runs a request with live per-stage progress; stores results in session state."""
    st.session_state.error = None
    st.session_state.stages = None
    st.session_state.request = request_text
    session_id = f"session-{uuid.uuid4()}"

    started = time.time()
    done: set[str] = set()
    progress = st.progress(0.0, text="Starting…")
    status = st.status("Planning your trip — several agents run in sequence…", expanded=True)

    def on_stage(author: str, times_spoken: int) -> None:
        label = STAGE_LABELS[author]
        if times_spoken == 1:
            status.write(f"✅ {label}")
        else:
            status.write(f"🔁 {label} — revision round {times_spoken}")
        done.add(author)
        progress.progress(
            len(done) / len(STAGE_LABELS),
            text=f"{len(done)} of {len(STAGE_LABELS)} stages complete",
        )

    try:
        st.session_state.stages = asyncio.run(
            run_trip_request(get_runner(), session_id, request_text, on_stage)
        )
        st.session_state.elapsed = time.time() - started
        status.update(label="Trip plan ready", state="complete", expanded=False)
    except Exception as exc:  # noqa: BLE001 - surface any provider/config error to the UI
        st.session_state.error = str(exc)
        status.update(label="The run failed", state="error", expanded=False)
    finally:
        progress.empty()


st.set_page_config(page_title="Travel Adviser", page_icon="🧳", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; max-width: 1100px; }
    div[data-testid="stMetric"] {
        background: rgba(128,128,128,0.08);
        border-radius: 10px;
        padding: 0.6rem 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

for key in ("stages", "error", "request", "elapsed"):
    st.session_state.setdefault(key, None)

# ---- Sidebar -------------------------------------------------------------
with st.sidebar:
    st.header("🧳 Travel Adviser")
    st.caption("Multi-agent trip planner built on Google ADK.")
    st.markdown("**Model fallback chain**")
    st.markdown("\n".join(f"{i}. `{m}`" for i, m in enumerate(fallback_chain(), 1)))
    st.markdown(
        f"- Budget revisions capped at **{MAX_BUDGET_ROUNDS}** rounds\n"
        f"- LLM calls capped at **{MAX_LLM_CALLS}** per request"
    )
    st.markdown("**Pipeline**")
    st.markdown("\n".join(f"{i}. {label}" for i, label in enumerate(STAGE_LABELS.values(), 1)))
    if st.session_state.stages or st.session_state.error:
        if st.button("↺ Start over", use_container_width=True):
            for key in ("stages", "error", "request", "elapsed"):
                st.session_state[key] = None
            st.rerun()

# ---- Header --------------------------------------------------------------
st.title("Plan your next trip")
st.caption("Tell it where, when, and how much — get an itinerary, flights, a hotel, and a budget check.")

# ---- Input ---------------------------------------------------------------
request_to_run = None
guided_tab, free_tab = st.tabs(["🧭 Guided", "✍️ Free text"])

with guided_tab:
    with st.form("guided_form"):
        left, right = st.columns(2)
        with left:
            surprise = st.checkbox("Surprise me — pick the destination for me")
            destination = st.text_input(
                "Destination", value="Kyoto, Japan", placeholder="e.g. Lisbon, Portugal"
            )
            origin = st.text_input(
                "Departing from (airport code)", value="JFK", max_chars=3,
                help="3-letter IATA code, e.g. JFK, LAX, LHR.",
            )
        with right:
            default_start = date.today() + timedelta(days=45)
            dates = st.date_input(
                "Travel dates",
                value=(default_start, default_start + timedelta(days=4)),
                min_value=date.today(),
            )
            one_way = st.checkbox("One-way trip (no return date)")
            budget = st.number_input(
                "Total budget (USD)", min_value=100, max_value=100_000, value=2500, step=100
            )
        interests = st.multiselect("Interests (optional)", INTERESTS)
        guided_submit = st.form_submit_button("Plan my trip", type="primary")

    if guided_submit:
        start = dates[0] if isinstance(dates, (tuple, list)) and dates else dates
        end = dates[1] if isinstance(dates, (tuple, list)) and len(dates) > 1 else None
        if not surprise and not destination.strip():
            st.warning("Enter a destination, or tick “Surprise me”.")
        elif len(origin.strip()) != 3:
            st.warning("Enter a 3-letter departure airport code, e.g. JFK.")
        elif not one_way and end is None:
            st.warning("Pick both a start and an end date (or tick one-way).")
        else:
            request_to_run = build_prompt(
                None if surprise else destination.strip(),
                origin.strip().upper(),
                start,
                end,
                one_way,
                int(budget),
                interests,
            )

with free_tab:
    with st.form("free_form"):
        free_text = st.text_area(
            "Describe the trip you want planned", value=EXAMPLE_REQUEST, height=110
        )
        free_submit = st.form_submit_button("Plan my trip", type="primary")
    if free_submit and free_text.strip():
        request_to_run = free_text.strip()

if request_to_run:
    execute(request_to_run)

# ---- Results -------------------------------------------------------------
if st.session_state.error:
    st.error(
        "The run failed — this is usually a provider quota/rate limit rather than "
        "a bug in the plan itself. Try again shortly, or add "
        "GEMINI_FALLBACK_MODEL / GROQ_API_KEY / OPENROUTER_API_KEY in `.env` for "
        "more fallback options."
    )
    with st.expander("Error details"):
        st.code(st.session_state.error, language=None)

stages = st.session_state.stages
if stages:
    st.divider()
    if st.session_state.request:
        st.caption(f"**Request:** {st.session_state.request}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Stages completed", f"{len(stages)} / {len(STAGE_LABELS)}")
    revisions = max(0, len(stages.get("budget_agent", [])) - 1)
    m2.metric("Budget revision rounds", revisions)
    m3.metric("Time taken", f"{(st.session_state.elapsed or 0):.0f}s")

    final = stages.get("final_merge_agent")
    if not final:
        st.warning(
            "The run didn't reach the final merge step — the tabs below show "
            "what did complete."
        )

    tab_keys = [k for k in reversed(STAGE_LABELS) if k in stages]  # final plan first
    tabs = st.tabs([STAGE_LABELS[k] for k in tab_keys])
    for tab, key in zip(tabs, tab_keys):
        with tab:
            st.markdown(stages[key][-1])  # latest revision is the current plan
            if len(stages[key]) > 1:
                with st.expander(f"Earlier revisions ({len(stages[key]) - 1})"):
                    for i, text in enumerate(stages[key][:-1], 1):
                        st.markdown(f"**Round {i}**")
                        st.markdown(text)
                        st.divider()

    if final:
        st.download_button(
            "⬇ Download plan (.md)",
            data=final[-1],
            file_name="trip_plan.md",
            mime="text/markdown",
        )
