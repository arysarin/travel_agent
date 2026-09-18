"""Itinerary Planning Agent — pure LLM reasoning, no tools."""

from google.adk.agents import Agent

from ..model_provider import get_model

itinerary_agent = Agent(
    name="itinerary_agent",
    model=get_model(),
    description=(
        "Builds the DAY-BY-DAY plan (sightseeing sequence, pacing, travel "
        "time vs. activity time) once a destination and trip length are "
        "known. Does not search flights or hotels, and does not check "
        "weather — those belong to other agents."
    ),
    instruction=(
        "Given a destination and a number of days, produce a day-by-day "
        "itinerary. Sequence activities to minimize backtracking, balance "
        "travel time against time actually spent at each place, and note "
        "which day (if any) is a pure travel/transit day. If asked to "
        "revise an existing itinerary to cut cost (e.g. drop a paid "
        "activity or a side trip), make the smallest change that meets the "
        "requested savings and clearly state what was removed or changed."
    ),
)
