"""Budget Optimization Agent.

aggregate_costs/check_budget are deterministic (see tools/budget.py) — the
only LLM work here is turning an overage into specific, actionable cuts.
This agent is meant to run as one member of the Coordinator's
planning_loop_agent (see agent.py), alongside itinerary_agent,
transportation_agent, and accommodation_agent, so that a proposed cut can
actually be applied by those agents on the next loop iteration rather than
just reported.
"""

from google.adk.agents import Agent
from google.adk.tools import ToolContext

from ..logging_utils import log_call
from ..model_provider import get_model
from ..tools.budget import aggregate_costs, check_budget


@log_call("tool_call")
def exit_budget_loop(tool_context: ToolContext) -> dict:
    """Signal that the plan is within budget and the revision loop can stop.

    Call this only after check_budget reports over_budget=False. Calling it
    ends the loop immediately instead of spending another revision round.
    """
    tool_context.actions.escalate = True
    return {"status": "loop_exit_requested"}


budget_agent = Agent(
    name="budget_agent",
    model=get_model(),
    description=(
        "Aggregates trip COSTS (flights, hotels, food, local transport, "
        "activities), checks them against the stated budget, and proposes "
        "specific cuts when over budget. Does not itself change flights, "
        "hotels, or the itinerary — it states what needs to change so the "
        "itinerary, transportation, and accommodation agents can revise "
        "their own outputs on the next round."
    ),
    instruction=(
        "1. Call aggregate_costs with the cost components gathered so far "
        "from the other agents' outputs (ask for reasonable estimates for "
        "any component, like food or local transport, that wasn't "
        "explicitly quoted).\n"
        "2. Call check_budget with the resulting total and the user's "
        "stated budget cap.\n"
        "3. If over_budget is False, call exit_budget_loop and report the "
        "final cost breakdown as within budget.\n"
        "4. If over_budget is True, do NOT call exit_budget_loop. Instead, "
        "propose 1-3 concrete, specific cuts that would close the gap "
        "(e.g. 'switch to a $80/night hotel instead of $150/night', or "
        "'drop the day-4 side trip') and clearly state which part of the "
        "plan (hotel, flight, or itinerary) needs to change and by roughly "
        "how much, so that agent revises its own earlier output on the "
        "next round instead of repeating it unchanged."
    ),
    tools=[aggregate_costs, check_budget, exit_budget_loop],
)
