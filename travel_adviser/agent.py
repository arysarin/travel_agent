"""Travel Adviser Coordinator — composes the six sub-agents from the spec.

This is a fixed SequentialAgent pipeline, not an LLM-routed
coordinator/dispatcher. `transfer_to_agent` (ADK's dispatcher pattern) hands
off the *entire rest of the turn* to its target — control doesn't return to
the caller to make further routing decisions within that same turn. An
earlier version of this file used a top-level `Agent` whose instructions
tried to transfer through destination_agent, then planning_loop_agent, then
weather_agent, then merge — `adk eval` caught that the run completed
without error but weather_agent never fired: the first transfer's target
became the final answer. Since every request here needs the *same* fixed
sequence of steps (not a choice between alternative specialists, which is
what the dispatcher pattern is for), a plain pipeline is the correct ADK
primitive, with `final_merge_agent` as its explicit last step.

`planning_loop_agent` is the one place real branching happens: it bundles
itinerary/flight/hotel generation with the budget check so that an
over-budget result actually gets revised, capped at MAX_BUDGET_ROUNDS
rounds instead of looping forever.
"""

from google.adk.agents import LoopAgent, SequentialAgent

from .config import MAX_BUDGET_ROUNDS
from .sub_agents.accommodation import accommodation_agent
from .sub_agents.budget import budget_agent
from .sub_agents.destination import destination_agent
from .sub_agents.final_merge import final_merge_agent
from .sub_agents.itinerary import itinerary_agent
from .sub_agents.transportation import transportation_agent
from .sub_agents.weather import weather_agent

planning_loop_agent = LoopAgent(
    name="planning_loop_agent",
    description=(
        "Builds the day-by-day itinerary, flight options, and hotel "
        "options for a known destination, then checks the total cost "
        "against the traveler's budget — revising and rechecking up to "
        f"{MAX_BUDGET_ROUNDS} times if it's over budget."
    ),
    sub_agents=[itinerary_agent, transportation_agent, accommodation_agent, budget_agent],
    max_iterations=MAX_BUDGET_ROUNDS,
)

root_agent = SequentialAgent(
    name="travel_adviser_coordinator",
    description=(
        "Coordinates end-to-end trip planning: destination, itinerary, "
        "flights, hotels, budget enforcement, and weather/risk notes."
    ),
    sub_agents=[destination_agent, planning_loop_agent, weather_agent, final_merge_agent],
)
