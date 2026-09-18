"""Destination Recommendation Agent — pure LLM reasoning, no tools."""

from google.adk.agents import Agent

from ..model_provider import get_model

destination_agent = Agent(
    name="destination_agent",
    model=get_model(),
    description=(
        "Recommends WHERE to go. Only handles picking or scoring candidate "
        "destinations against the traveler's stated budget and interests "
        "(e.g. 'surprise me', 'somewhere warm under $2000'). Does not plan "
        "flights, hotels, day-by-day activities, or check weather — those "
        "belong to other agents."
    ),
    instruction=(
        "You recommend travel destinations based on the traveler's stated "
        "budget, interests, trip length, and any other preferences.\n\n"
        "If the user already named a specific destination, do not "
        "second-guess it — reply with exactly one short line confirming it "
        "(e.g. 'Destination confirmed: Kyoto, Japan.') and nothing else. "
        "This step always runs, so keep it a near no-op when a destination "
        "is already given rather than re-deciding it.\n\n"
        "Otherwise, propose 1-3 well-reasoned destination options with a "
        "one-line rationale each, then pick the best fit and state it "
        "clearly as your final answer."
    ),
)
