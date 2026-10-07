import pytest

from src.modeling import WeeklyTable, correlations, describe_trend, fit_regression, forecast_next_week
from tests.conftest import requires_data


def synthetic(columns: dict[str, list[float]]) -> WeeklyTable:
    n = len(next(iter(columns.values())))
    weeks = list(range(1, n + 1))
    return WeeklyTable(weeks=weeks, rows={w: {k: v[i] for k, v in columns.items()} for i, w in enumerate(weeks)})


def test_regression_recovers_a_known_slope():
    x = [10, 12, 15, 11, 18, 20, 22, 19, 25, 27]
    y = [2 * v + 5 + noise for v, noise in zip(x, [0.3, -0.2, 0.1, -0.4, 0.2, 0.0, -0.1, 0.3, -0.3, 0.1])]
    fit = fit_regression(synthetic({"revenue": y, "employees": x}), "revenue", ["employees"])
    assert fit["status"] == "ok"
    assert fit["coefficients"][0]["coefficient"] == pytest.approx(2.0, abs=0.05)
    assert fit["intercept"] == pytest.approx(5.0, abs=0.7)
    assert fit["r_squared"] > 0.99 and fit["coefficients"][0]["significant_at_5pct"]
    assert any("exploratory" in c for c in fit["caveats"])


def test_regression_refuses_too_few_weeks():
    table = synthetic({"revenue": [1, 2, 3, 4, 5], "employees": [1, 2, 3, 5, 8]})
    assert fit_regression(table, "revenue", ["employees"])["status"] == "insufficient_data"
    table = synthetic({"revenue": [1, 2, 3, 4, 5, 6, 7], "employees": [1, 2, 3, 5, 8, 9, 10],
                       "avg_price": [5, 5, 5, 5, 5, 5, 5]})
    assert fit_regression(table, "revenue", ["employees", "avg_price"])["status"] == "insufficient_data"


def test_unknown_variable_is_reported():
    assert fit_regression(synthetic({"revenue": [1] * 8}), "revenue", ["moon phase"])["status"] == "not_found"


@requires_data
def test_weekly_table_has_derived_demand(table):
    row = table.rows[7]
    assert row["demand"] == row["cups_served"] + row["lost_customers"] == 3979 + 742
    assert row["demand_to_capacity"] == pytest.approx(4721 / 5013)
    assert table.value("employees") == 44.0  # latest week


@requires_data
def test_describe_trend_and_correlations(table):
    trend = describe_trend(table, "sales")  # alias of revenue
    assert trend["variable"] == "revenue" and trend["direction"] == "up" and trend["weeks_up"] == 13
    assert trend["biggest_rise"]["week"] == 14
    corr = correlations(table, "revenue")
    rs = [abs(c["r"]) for c in corr["correlations"]]
    assert rs == sorted(rs, reverse=True) and "cause" in corr["caveats"][-1]


@requires_data
def test_forecast_gives_a_range_and_its_past_error(table):
    forecast = forecast_next_week(table, "demand")
    assert forecast["status"] == "ok" and forecast["target_week"] == 15
    assert forecast["suggested"]["low"] <= forecast["suggested"]["point"] <= forecast["suggested"]["high"]
    assert set(forecast["typical_past_error"]) == {"recent_average", "linear_trend"}
