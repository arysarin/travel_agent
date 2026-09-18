"""Final Merge step — combines every prior stage's output into one answer.

`transfer_to_agent` (used for the old LLM-routed coordinator design) hands
off the *entire rest of the turn* to its target; control doesn't return to
the caller for further routing within the same turn. That means a
coordinator that tries to transfer through destination_agent, then
planning_loop_agent, then weather_agent in sequence never gets to the third
step — the first transfer's target's own output becomes the final answer,
silently dropping the weather section (confirmed via `adk eval`: the run
completed with no errors, but weather_agent never fired).

The fix is running the whole pipeline as one deterministic SequentialAgent
(see agent.py) instead of chained LLM-decided transfers, with this agent as
the explicit last step that merges everything the earlier steps produced
(all visible in this invocation's shared conversation history) into the
one structured response the spec's functional requirements ask for.
"""

from google.adk.agents import Agent

from ..config import MAX_BUDGET_ROUNDS
from ..model_provider import get_model

final_merge_agent = Agent(
    name="final_merge_agent",
    model=get_model(),
    description=(
        "Merges the destination, itinerary, flights, hotel, budget, and "
        "weather outputs already produced earlier in this conversation "
        "into one final structured trip recommendation."
    ),
    instruction=(
        "Earlier steps in this conversation already produced: a confirmed "
        "or chosen destination, a day-by-day itinerary, flight options, "
        "hotel options, a cost breakdown and budget check, and a weather "
        "forecast. Do not call any tools and do not re-derive any of "
        "this — merge what already happened into one final response with "
        "exactly these sections: Destination, Day-by-Day Itinerary, "
        "Flights, Hotel, Total Cost Breakdown, and Weather & Safety "
        "Notes.\n\n"
        "If the cost breakdown is still over budget after "
        f"{MAX_BUDGET_ROUNDS} revision rounds, say so plainly in the Total "
        "Cost Breakdown section rather than hiding it, and state the "
        "closest achievable total.\n\n"
        "Never fabricate flight prices, hotel prices, or weather data — "
        "only report what was actually produced earlier in this "
        "conversation."
    ),
)
