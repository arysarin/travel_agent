from travel_adviser.tools.budget import aggregate_costs, check_budget


def test_aggregate_costs_sums_components():
    result = aggregate_costs(
        flight_cost=800,
        hotel_cost_per_night=100,
        num_nights=4,
        food_cost_per_day=50,
        local_transport_per_day=20,
        activities_cost=150,
        num_days=5,
    )
    assert result["hotel_total"] == 400
    assert result["food_total"] == 250
    assert result["local_transport_total"] == 100
    assert result["total"] == 800 + 400 + 250 + 100 + 150


def test_check_budget_within_cap():
    result = check_budget(total_cost=2000, budget_cap=2500)
    assert result["over_budget"] is False
    assert result["overage"] == 0


def test_check_budget_over_cap():
    result = check_budget(total_cost=2800, budget_cap=2500)
    assert result["over_budget"] is True
    assert result["overage"] == 300
