"""Streamlit demo UI for Travel Adviser.

Runs the agent in-process via ADK's InMemoryRunner rather than spawning a
separate `adk api_server` — one process, one `streamlit run` command, no
extra moving parts. Each request runs the whole pipeline; progress is shown
live per stage as each agent finishes, and the results are rendered once
the run completes.
"""

import asyncio
import logging
import time
import uuid
from datetime import date, timedelta

import streamlit as st
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from travel_adviser.agent import root_agent
from travel_adviser.airports import airport_labels, code_from_label, default_label
from travel_adviser.emailer import EmailError, email_configured, is_valid_address, send_plan_email
from travel_adviser.tools.weather_window import format_suggestions_markdown, suggest_better_dates
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

QUICK_DESTINATIONS = [
    "Darjeeling, India",
    "Goa, India",
    "Jaipur, India",
    "Munnar, Kerala, India",
    "Rishikesh, India",
    "Ladakh, India",
    "Kyoto, Japan",
    "Bali, Indonesia",
]

# Fixed, approximate rates — not live. Good enough for a budget instruction
# to the agents (which still reason in USD, since that's what SerpAPI/
# Amadeus flight and hotel prices come back in); not a real conversion tool.
CURRENCY_RATES_PER_USD = {"USD": 1.0, "INR": 83.0}
BUDGET_DEFAULTS = {  # (default, min, max, step)
    "USD": (2500, 100, 100_000, 100),
    "INR": (200_000, 5_000, 8_000_000, 5_000),
}


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


def build_prompt(destination, origin, start, end, one_way, budget, currency, interests):
    """Turns the guided-form fields into the natural-language request.

    The pipeline's tools (SerpAPI/Amadeus flight and hotel prices,
    aggregate_costs/check_budget) all work in USD, so a non-USD budget is
    converted to its approximate USD equivalent for the actual constraint —
    the original currency and amount are included too so the agents can
    still mention it, but the number they compute against stays USD.
    """
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
    if currency == "USD":
        parts.append(f"under ${budget:,} total")
    else:
        usd_budget = round(budget / CURRENCY_RATES_PER_USD[currency])
        parts.append(
            f"under {currency} {budget:,} total (approximately ${usd_budget:,} USD "
            f"at ~{CURRENCY_RATES_PER_USD[currency]:.0f} {currency}/USD — treat "
            f"${usd_budget:,} as the actual budget cap, but also state the total "
            f"in {currency} in the final plan)"
        )
    prompt = ", ".join(parts) + "."
    if interests:
        prompt += f" Interests: {', '.join(i.lower() for i in interests)}."
    return prompt


MAX_EMAILS_PER_SESSION = 5
EMAIL_HELP = (
    "Optional. The finished plan is emailed here once it's ready."
    if email_configured()
    else "Email isn't set up on this server (SMTP_USER / SMTP_PASSWORD missing)."
)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_weather_check(destination: str, start_iso: str, end_iso: str) -> dict:
    return suggest_better_dates(destination, start_iso, end_iso)


def plan_markdown(final_text: str) -> str:
    """The final plan plus, when the chosen dates have poor weather, better-date suggestions."""
    extra = format_suggestions_markdown(st.session_state.get("weather_check"))
    return f"{final_text}\n\n{extra}" if extra else final_text


def email_plan(to: str, final_text: str) -> tuple[bool, str]:
    """Sends the plan; returns (ok, message) for display. Caps sends per browser session."""
    if st.session_state.email_count >= MAX_EMAILS_PER_SESSION:
        return False, f"You've reached the limit of {MAX_EMAILS_PER_SESSION} emails for this session."
    trip = st.session_state.get("trip") or {}
    subject = f"Your trip plan: {trip['destination']}" if trip.get("destination") else "Your trip plan"
    try:
        send_plan_email(to, subject, plan_markdown(final_text))
    except EmailError as exc:
        return False, str(exc)
    st.session_state.email_count += 1
    return True, f"Plan emailed to {to.strip()}."


def render_weather_check(check: dict | None) -> None:
    if not check:
        return
    if "error" in check:
        st.caption(f"Seasonal weather check unavailable: {check['error']}")
        return
    q = check["requested"]
    if check["weather_is_good"]:
        st.success(
            f"☀️ Weather looks good for your dates: typically {q['avg_temp_c']}°C with "
            f"about {q['expected_rainy_days']} rainy days."
        )
    else:
        st.warning(
            f"🌧️ Weather for {q['start']} to {q['end']} is typically **{q['rating']}** "
            f"({q['avg_temp_c']}°C, about {q['expected_rainy_days']} rainy days)."
        )
        if check["suggested_windows"]:
            st.markdown("**Better dates to consider:**")
            for w in check["suggested_windows"]:
                st.markdown(
                    f"- **{w['start']} → {w['end']}** — {w['rating']}, "
                    f"~{w['expected_rainy_days']} rainy days, {w['avg_temp_c']}°C"
                )
            st.caption("Flight and hotel prices aren't re-checked for these dates.")
        else:
            st.caption("No clearly better window was found near your dates.")
    st.caption(f"Based on the {check['basis']}.")


def fallback_chain() -> list[str]:
    chain = [MODEL_NAME]
    if GEMINI_FALLBACK_MODEL:
        chain.append(GEMINI_FALLBACK_MODEL)
    if GROQ_API_KEY:
        chain.append("Groq")
    if OPENROUTER_API_KEY:
        chain.append("OpenRouter")
    return chain


def execute(request_text: str, trip: dict | None = None, email_to: str = "") -> None:
    """Runs a request with live per-stage progress; stores results in session state.

    `trip` (guided form only) is {destination, start, end}; when it names a
    destination, typical weather for those dates is checked up front, outside
    the LLM pipeline, so the better-dates advice shows even if a model run fails.
    """
    st.session_state.error = None
    st.session_state.stages = None
    st.session_state.request = request_text
    st.session_state.trip = trip
    st.session_state.weather_check = None
    st.session_state.email_status = None
    session_id = f"session-{uuid.uuid4()}"

    if trip and trip.get("destination"):
        with st.spinner("Checking typical weather for your dates…"):
            st.session_state.weather_check = cached_weather_check(
                trip["destination"], trip["start"].isoformat(), trip["end"].isoformat() if trip.get("end") else ""
            )

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
        final = st.session_state.stages.get("final_merge_agent")
        if email_to and final:
            st.session_state.email_status = email_plan(email_to, final[-1])
        elif email_to:
            st.session_state.email_status = (False, "The run didn't finish the full plan, so nothing was emailed.")
    except Exception as exc:  # noqa: BLE001 - surface any provider/config error to the UI
        # str(exc) can be empty for some exception types (e.g. a bare
        # asyncio.CancelledError/TimeoutError), and an empty string reads
        # as falsy — without the fallback, the UI would show the failed
        # status but silently drop the error message entirely.
        st.session_state.error = str(exc) or f"{type(exc).__module__}.{type(exc).__name__}"
        logging.getLogger(__name__).exception("Trip planning run failed")
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

RESULT_KEYS = ("stages", "error", "request", "elapsed", "trip", "weather_check", "email_status")
for key in RESULT_KEYS:
    st.session_state.setdefault(key, None)
st.session_state.setdefault("email_count", 0)
# Widgets below read/write these via `key=` instead of a hardcoded `value=`
# — passing a literal `value=` on every rerun (e.g. a freshly computed
# date range) fights the widget's own state and can silently reset
# whatever the user just picked before they finish interacting with it.
st.session_state.setdefault("destination_input", "Kyoto, Japan")
_default_start = date.today() + timedelta(days=45)
st.session_state.setdefault("travel_dates", (_default_start, _default_start + timedelta(days=4)))

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
            for key in RESULT_KEYS:
                st.session_state[key] = None
            st.rerun()

# ---- Header --------------------------------------------------------------
st.title("Plan your next trip")
st.caption("Tell it where, when, and how much — get an itinerary, flights, a hotel, and a budget check.")

# ---- Input ---------------------------------------------------------------
request_to_run = None
trip = None
email_to = ""
guided_tab, free_tab = st.tabs(["🧭 Guided", "✍️ Free text"])

with guided_tab:
    st.caption("Quick-pick a destination")
    quick_cols = st.columns(4)
    for i, quick_dest in enumerate(QUICK_DESTINATIONS):
        if quick_cols[i % 4].button(quick_dest, key=f"quickdest_{quick_dest}", use_container_width=True):
            st.session_state["destination_input"] = quick_dest
            st.session_state["surprise_checkbox"] = False

    # Currency lives outside the form: widgets inside st.form don't rerun
    # until submit, but the budget field's own range needs to update the
    # moment currency changes, not a submit later.
    currency = st.selectbox("Currency", list(CURRENCY_RATES_PER_USD), key="currency_select")
    budget_default, budget_min, budget_max, budget_step = BUDGET_DEFAULTS[currency]

    with st.form("guided_form"):
        left, right = st.columns(2)
        with left:
            surprise = st.checkbox("Surprise me — pick the destination for me", key="surprise_checkbox")
            destination = st.text_input(
                "Destination", key="destination_input", placeholder="e.g. Lisbon, Portugal"
            )
            origin_label = st.selectbox(
                "Departing from",
                airport_labels(),
                index=airport_labels().index(default_label()),
                key="origin_airport",
                help="Click and type a city or airport name (e.g. Delhi, Mumbai, London).",
            )
        with right:
            dates = st.date_input("Travel dates", key="travel_dates", min_value=date.today())
            one_way = st.checkbox("One-way trip (no return date)")
            budget = st.number_input(
                f"Total budget ({currency})",
                min_value=budget_min,
                max_value=budget_max,
                value=budget_default,
                step=budget_step,
                key=f"budget_input_{currency}",
            )
            if currency != "USD":
                st.caption(
                    f"≈ ${round(budget / CURRENCY_RATES_PER_USD[currency]):,} USD "
                    f"at an approximate, non-live rate."
                )
        interests = st.multiselect("Interests (optional)", INTERESTS)
        guided_email = st.text_input(
            "Email me the plan", key="guided_email", placeholder="you@example.com",
            help=EMAIL_HELP, disabled=not email_configured(),
        )
        guided_submit = st.form_submit_button("Plan my trip", type="primary")

    if guided_submit:
        start = dates[0] if isinstance(dates, (tuple, list)) and dates else dates
        end = dates[1] if isinstance(dates, (tuple, list)) and len(dates) > 1 else None
        if not surprise and not destination.strip():
            st.warning("Enter a destination, or tick “Surprise me”.")
        elif not one_way and end is None:
            st.warning("Pick both a start and an end date (or tick one-way).")
        elif guided_email.strip() and not is_valid_address(guided_email.strip()):
            st.warning("That email address doesn't look valid.")
        else:
            email_to = guided_email.strip()
            trip = {"destination": None if surprise else destination.strip(), "start": start, "end": None if one_way else end}
            request_to_run = build_prompt(
                None if surprise else destination.strip(),
                code_from_label(origin_label),
                start,
                end,
                one_way,
                int(budget),
                currency,
                interests,
            )

with free_tab:
    with st.form("free_form"):
        free_text = st.text_area(
            "Describe the trip you want planned", value=EXAMPLE_REQUEST, height=110
        )
        free_email = st.text_input(
            "Email me the plan", key="free_email", placeholder="you@example.com",
            help=EMAIL_HELP, disabled=not email_configured(),
        )
        free_submit = st.form_submit_button("Plan my trip", type="primary")
    if free_submit and free_text.strip():
        if free_email.strip() and not is_valid_address(free_email.strip()):
            st.warning("That email address doesn't look valid.")
        else:
            email_to = free_email.strip()
            request_to_run = free_text.strip()

if request_to_run:
    if email_to:
        st.session_state["resend_email"] = email_to
    execute(request_to_run, trip=trip, email_to=email_to)

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

render_weather_check(st.session_state.weather_check)

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
            data=plan_markdown(final[-1]),
            file_name="trip_plan.md",
            mime="text/markdown",
        )
        st.subheader("📧 Email this plan")
        sent = st.session_state.email_status
        if sent:
            (st.success if sent[0] else st.error)(sent[1])
        if email_configured():
            send_to = st.text_input("Send to", key="resend_email", placeholder="you@example.com")
            if st.button("Send email"):
                if not is_valid_address(send_to.strip()):
                    st.session_state.email_status = (False, "That email address doesn't look valid.")
                else:
                    with st.spinner("Sending…"):
                        st.session_state.email_status = email_plan(send_to.strip(), final[-1])
                st.rerun()
        else:
            st.caption("Email isn't set up on this server, so plans can only be downloaded.")
