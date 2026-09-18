"""Weather & Risk Assessment Agent — forecast via OpenWeatherMap."""

from google.adk.agents import Agent

from ..model_provider import get_model
from ..tools.weather import get_weather

weather_agent = Agent(
    name="weather_agent",
    model=get_model(),
    description=(
        "Handles WEATHER forecasts, seasonal notes, and general travel "
        "safety/risk advisories for the destination. Does not book "
        "anything and does not plan the itinerary or budget."
    ),
    instruction=(
        "Use the get_weather tool to fetch a forecast for the destination "
        "and trip dates. Summarize expected conditions and flag anything "
        "that should change packing or plans (e.g. rain, extreme heat). "
        "If the tool reports the dates are outside the forecast window, "
        "give a general seasonal expectation instead and say the forecast "
        "is unavailable that far out. Note any general safety advisories "
        "you are aware of for the destination, without fabricating "
        "specific incidents."
    ),
    tools=[get_weather],
)
