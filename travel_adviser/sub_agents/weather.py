"""Weather & Risk Assessment Agent — forecast via OpenWeatherMap, seasonal check via Open-Meteo."""

from google.adk.agents import Agent

from ..model_provider import get_model
from ..tools.weather import get_weather
from ..tools.weather_window import suggest_better_dates

weather_agent = Agent(
    name="weather_agent",
    model=get_model(),
    description=(
        "Handles WEATHER forecasts, seasonal notes, and general travel "
        "safety/risk advisories for the destination, and suggests better "
        "travel dates when the weather for the chosen dates is poor. Does "
        "not book anything and does not plan the itinerary or budget."
    ),
    instruction=(
        "Do both of these for the destination and trip dates:\n"
        "1. Call get_weather to fetch a forecast. Summarize expected "
        "conditions and flag anything that should change packing or plans "
        "(e.g. rain, extreme heat). If the tool reports the dates are "
        "outside the forecast window, say the forecast is unavailable that "
        "far out and rely on step 2 for the seasonal expectation.\n"
        "2. Call suggest_better_dates with the destination, start date, and "
        "end date (YYYY-MM-DD). Report the typical weather for the chosen "
        "dates. If weather_is_good is false, add a clearly labelled "
        "'Better travel dates' list with each suggested window's dates, "
        "rating, expected rainy days, and average temperature, and note "
        "that flight and hotel prices were not re-checked for those dates. "
        "If it returns an error, say the seasonal check was unavailable "
        "and do not guess at alternative dates.\n\n"
        "Describe suggest_better_dates results as seasonal averages from "
        "past years, not a forecast. Note any general safety advisories you "
        "are aware of for the destination, without fabricating specific "
        "incidents."
    ),
    tools=[get_weather, suggest_better_dates],
)
