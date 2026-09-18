"""Transportation Agent — flight search via SerpAPI, with Amadeus backup."""

from google.adk.agents import Agent

from ..model_provider import get_model
from ..tools.flights import search_flights

transportation_agent = Agent(
    name="transportation_agent",
    model=get_model(),
    description=(
        "Handles FLIGHTS and routes BETWEEN cities/countries (getting the "
        "traveler to and from the destination). Does not handle hotels, "
        "lodging, or in-destination activities — those belong to other "
        "agents."
    ),
    instruction=(
        "Use the search_flights tool to find flight options between the "
        "origin and destination on the given dates. Always pass the exact "
        "3-letter IATA airport code for origin/destination (e.g. 'JFK', "
        "not 'New York') — the tool's Amadeus backup requires it, even "
        "though its primary source tolerates looser input. Recommend the "
        "best option balancing price, duration, and number of stops, and "
        "state its price clearly since the Budget agent depends on it. If "
        "the tool returns an error, say so plainly and give a rough "
        "estimated price range instead of failing the whole plan."
    ),
    tools=[search_flights],
)
