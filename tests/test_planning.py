import pytest

from src.planning import compare_scenarios, evaluate_scenario, plan_next_week
from tests.conftest import requires_data

pytestmark = requires_data


def test_baseline_reproduces_the_latest_week(table):
    result = evaluate_scenario(table, {})
    base = result["baseline_next_week"]
    assert base["cups_served"] == pytest.approx(table.value("cups_served"), rel=1e-3)
    assert base["revenue"] == pytest.approx(table.value("revenue"), rel=1e-3)
    assert result["difference_vs_baseline"]["net_income_change"] == 0


def test_more_employees_means_more_capacity_and_more_payroll(table):
    result = evaluate_scenario(table, {"extra_employees": 4})
    diff = result["difference_vs_baseline"]
    assert diff["employees"] == 4 and diff["weekly_capacity"] > 0 and diff["payroll"] > 0
    assert diff["lost_customers"] < 0 and diff["cups_served"] > 0  # fewer customers walk away
    assert result["scenario_next_week"]["wait_time_satisfaction"] >= result["baseline_next_week"]["wait_time_satisfaction"]
    assert any("outside anything tried" in w for w in result["warnings"])


def test_price_rise_uses_an_explicit_elasticity_assumption(table):
    result = evaluate_scenario(table, {"price_change_pct": 5})
    assert result["difference_vs_baseline"]["demand"] < 0
    assert any("assumption" in w for w in result["warnings"])
    stronger = evaluate_scenario(table, {"price_change_pct": 5}, {"elasticity": -2.0})
    assert stronger["difference_vs_baseline"]["demand"] < result["difference_vs_baseline"]["demand"]


def test_bad_inputs_are_errors(table):
    assert evaluate_scenario(table, {"robots": 3})["status"] == "error"
    assert evaluate_scenario(table, {"employees": 0})["status"] == "error"
    assert compare_scenarios(table, [], objective="fun")["status"] == "error"


def test_scenarios_are_ranked_on_the_objective(table):
    result = compare_scenarios(table, [{"name": "more staff", "changes": {"extra_employees": 2}},
                                       {"name": "hold", "changes": {}}], objective="cups_served")
    values = [r["objective_value"] for r in result["ranking"]]
    assert values == sorted(values, reverse=True)
    assert result["ranking"][0]["name"] == "more staff"


def test_plan_bundles_situation_signals_and_ranking(db, table):
    plan = plan_next_week(db, table, objective="net_income")
    assert plan["status"] == "ok" and plan["target_week"] == 15
    assert "revenue" in plan["situation"] and plan["demand_forecast"]["point"] > 0
    assert plan["scenario_ranking"][0]["rank"] == 1 and plan["suggestions"]
    assert plan_next_week(db, table, objective="world peace")["status"] == "error"
