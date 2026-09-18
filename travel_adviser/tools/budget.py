"""Deterministic budget arithmetic — no network calls, no LLM.

Kept as plain functions per the spec's own note: aggregation and
threshold-checking is deterministic arithmetic and doesn't need to be
forced through an LLM call just because the architecture diagram draws it
as an agent box.
"""

from ..logging_utils import log_call


@log_call("tool_call")
def aggregate_costs(
    flight_cost: float,
    hotel_cost_per_night: float,
    num_nights: int,
    food_cost_per_day: float,
    local_transport_per_day: float,
    activities_cost: float,
    num_days: int,
) -> dict:
    """Sum all trip cost components into a total.

    Args:
        flight_cost: Total round-trip flight cost in USD.
        hotel_cost_per_night: Hotel price per night in USD.
        num_nights: Number of nights booked.
        food_cost_per_day: Estimated food spend per day in USD.
        local_transport_per_day: Estimated local transport spend per day in USD.
        activities_cost: Total cost of planned activities/sightseeing in USD.
        num_days: Trip length in days (used for food/local-transport totals).

    Returns:
        A dict with the per-component breakdown and the "total" cost.
    """
    hotel_total = hotel_cost_per_night * num_nights
    food_total = food_cost_per_day * num_days
    transport_total = local_transport_per_day * num_days
    total = flight_cost + hotel_total + food_total + transport_total + activities_cost
    return {
        "flight_cost": flight_cost,
        "hotel_total": hotel_total,
        "food_total": food_total,
        "local_transport_total": transport_total,
        "activities_cost": activities_cost,
        "total": round(total, 2),
    }


@log_call("tool_call")
def check_budget(total_cost: float, budget_cap: float) -> dict:
    """Check whether a total cost is within a budget cap.

    Args:
        total_cost: The trip's total cost in USD, e.g. from aggregate_costs.
        budget_cap: The user's stated budget ceiling in USD.

    Returns:
        A dict with "over_budget" (bool) and "overage" (USD amount over
        the cap, 0 if within budget).
    """
    overage = round(max(total_cost - budget_cap, 0), 2)
    return {"over_budget": overage > 0, "overage": overage, "total_cost": total_cost, "budget_cap": budget_cap}
