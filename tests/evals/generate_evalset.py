"""Builds travel_adviser.evalset.json from the CASES list below.

Run this after adding/editing a case (rather than hand-editing the JSON,
which has to match ADK's pydantic eval schema exactly):

    .venv\\Scripts\\python.exe tests\\evals\\generate_evalset.py

The coordinator (agent.py) is a plain SequentialAgent pipeline, not an
LLM-routed dispatcher, so which agents run is structurally fixed by code,
not worth asserting here. What each case instead checks is that the real
tool calls a full run should make (search_flights/search_hotels from
planning_loop_agent, then get_weather from weather_agent) actually happen
in order, via tool_trajectory_avg_score with IN_ORDER + ignore_args
matching (see test_config.json) — args aren't compared since dates/prices
vary per run. This is a direct regression guard for the exact bug that
motivated the SequentialAgent rewrite: a run that silently stops before
weather_agent (no error, just a missing final section) shows up here as
get_weather never being called.
"""

import json
from pathlib import Path

from google.adk.evaluation.eval_case import EvalCase, IntermediateData, Invocation
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types


def user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def tool_call(name: str) -> types.FunctionCall:
    return types.FunctionCall(name=name, args={})


# Every full run should call these, in this order, regardless of the
# specific request (planning_loop_agent's search calls, then weather_agent's).
DEFAULT_EXPECTED_TOOLS = ["search_flights", "search_hotels", "get_weather"]

# (eval_id, request text, expected tool-call order, manual-check note)
CASES = [
    (
        "destination_given_full_trip",
        "Plan a 5-day trip to Kyoto, Japan under $2500, departing JFK on "
        "2026-11-10 and returning 2026-11-15.",
        DEFAULT_EXPECTED_TOOLS,
        "Baseline happy path from the README example.",
    ),
    (
        "surprise_me_destination",
        "Surprise me with a warm beach destination for 4 days under $1500, "
        "departing from Chicago on 2026-12-05.",
        DEFAULT_EXPECTED_TOOLS,
        "No destination named — check destination_agent actually proposes "
        "one instead of stalling (it always runs now, but should do "
        "real work here vs. the one-line confirm it gives when a "
        "destination is already given).",
    ),
    (
        "tight_budget_forces_revision",
        "Plan a 3-day trip to Paris under $500 total, departing from Boston "
        "on 2026-10-20 and returning 2026-10-23.",
        DEFAULT_EXPECTED_TOOLS,
        "Budget is unrealistic for the destination — check the budget loop "
        "actually revises the plan and, if still over budget after "
        "MAX_BUDGET_ROUNDS, says so plainly instead of hiding it.",
    ),
    (
        "one_way_trip",
        "Plan a one-way move to Berlin for a new job, departing from Austin "
        "on 2027-01-15. Budget is $3000 for the flight and first two weeks "
        "of temporary housing.",
        DEFAULT_EXPECTED_TOOLS,
        "No return date — check transportation_agent handles a one-way "
        "search instead of assuming round-trip.",
    ),
    (
        "far_future_weather_unavailable",
        "Plan a 4-day trip to Rome under $2000, departing from Miami on "
        "2027-03-01 and returning 2027-03-05.",
        DEFAULT_EXPECTED_TOOLS,
        "Dates are well beyond OpenWeatherMap's 5-day free-tier forecast — "
        "check weather_agent gives a seasonal note instead of a fabricated "
        "forecast.",
    ),
    (
        "domestic_short_trip",
        "Plan a quick weekend trip from New York to Miami, 2 days, under "
        "$800, departing 2026-10-24 and returning 2026-10-26.",
        DEFAULT_EXPECTED_TOOLS,
        "Short/simple domestic case — cheap to re-run often for a smoke "
        "check.",
    ),
    (
        "multi_interest_destination_given",
        "Destination will be Darjeeling. Dates will be October 10th 2026 "
        "for 3 days. My budget is 10000. My interests are adventure, "
        "culture, food, outdoor activities.",
        DEFAULT_EXPECTED_TOOLS,
        "Mirrors the exact request that surfaced the Groq reasoning_content "
        "bug during manual testing — good regression guard for that fix.",
    ),
    (
        "impossible_budget",
        "Plan a 5-day trip to Tokyo, Japan under $200 total, departing "
        "Seattle on 2026-11-20 and returning 2026-11-25.",
        DEFAULT_EXPECTED_TOOLS,
        "Budget is impossible for this destination — the final response "
        "must clearly state it's over budget with the closest achievable "
        "total, not silently present a fake $200 plan.",
    ),
]


def build_eval_set() -> EvalSet:
    eval_cases = []
    for eval_id, text, expected_tools, note in CASES:
        eval_cases.append(
            EvalCase(
                eval_id=eval_id,
                conversation=[
                    Invocation(
                        invocation_id=f"{eval_id}-1",
                        user_content=user_content(text),
                        intermediate_data=IntermediateData(
                            tool_uses=[tool_call(name) for name in expected_tools]
                        ),
                    )
                ],
                final_session_state={},
            )
        )
    return EvalSet(
        eval_set_id="travel_adviser_smoke",
        name="Travel Adviser smoke eval set",
        description=(
            "8 varied trip requests covering surprise-me destination, "
            "one-way flights, tight/impossible budgets, and far-future "
            "weather. See each case's `note` in generate_evalset.py for "
            "what to eyeball manually."
        ),
        eval_cases=eval_cases,
    )


if __name__ == "__main__":
    out_path = Path(__file__).parent / "travel_adviser.evalset.json"
    eval_set = build_eval_set()
    out_path.write_text(eval_set.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    print(f"Wrote {len(eval_set.eval_cases)} eval cases to {out_path}")
