"""Accommodation Agent — hotel search via SerpAPI Google Hotels."""

from google.adk.agents import Agent

from ..model_provider import get_model
from ..tools.hotels import search_hotels

accommodation_agent = Agent(
    name="accommodation_agent",
    model=get_model(),
    description=(
        "Handles HOTELS and lodging AT the destination (where to stay). "
        "Does not handle flights or routes between cities, and does not "
        "plan day-by-day activities — those belong to other agents."
    ),
    instruction=(
        "Use the search_hotels tool to find lodging options for the given "
        "location and date range. Recommend the best option balancing "
        "price per night, rating, and location, and state the price "
        "clearly since the Budget agent depends on it. If the tool returns "
        "an error, say so plainly and give a rough estimated nightly price "
        "range instead of failing the whole plan."
    ),
    tools=[search_hotels],
)
