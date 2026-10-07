import pytest

from src import analytics
from src.analytics import compute_change
from tests.conftest import requires_data

pytestmark = requires_data


def test_get_metric_with_everyday_names(db):
    revenue = analytics.get_metric(db, "revenue", 3)
    assert revenue["status"] == "ok" and revenue["value"] == 13048.0 and revenue["display"] == "$13,048.00"
    assert revenue["source"] == "Week 3/results-dashboard.xlsx [Dashboard!B5]"
    assert analytics.get_metric(db, "profit", 8)["metric"] == "Weekly Net Income"
    assert analytics.get_metric(db, "satisfaction", 7)["metric"] == "Customer Satisfaction"


def test_multi_company_metrics_default_to_our_cafe(db):
    ours = analytics.get_metric(db, "employees", 7)
    assert (ours["company"], ours["value"]) == ("Cafe A", 25.0)
    industry = analytics.get_metric(db, "survey satisfaction", 7, company="Industry Average")
    assert industry["status"] == "ok" and industry["company"] == "Industry Average"


def test_unknown_metric_gives_suggestions(db):
    result = analytics.get_metric(db, "gros margin", 7)
    assert result["status"] == "not_found"
    assert "gross margin" in result["suggestions"]
    missing = analytics.get_metric(db, "revenue", 99)
    assert missing["status"] == "not_found" and missing["weeks_with_data"] == list(range(1, 15))


def test_compare_metric_dollars(db):
    result = analytics.compare_metric(db, "revenue", 3, 8)
    assert result["absolute_change"] == pytest.approx(15741.42)
    assert result["percent_change"] == pytest.approx(120.64)
    assert result["direction"] == "increase"


def test_compare_metric_rate_reports_percentage_points(db):
    result = analytics.compare_metric(db, "customer satisfaction", 1, 14)
    assert result["percentage_point_change"] == pytest.approx(28.6)
    assert result["percent_change"] == pytest.approx(70.97, abs=0.01)


def test_compute_change_handles_zero_start():
    assert compute_change(0, 5, "USD")["percent_change"] is None
    assert compute_change(0.40, 0.50, "percent")["percentage_point_change"] == pytest.approx(10)


def test_trend_and_extreme_week(db):
    trend = analytics.metric_trend(db, "wait time", start_week=10)
    assert trend["weeks"] == [10, 11, 12, 13, 14]
    assert trend["points"][1]["change_from_previous_week"]["direction"] == "decrease"
    worst = analytics.find_extreme_week(db, "lost customers", mode="max")
    assert (worst["week"], worst["value"]) == (13, 1872.0)
    jump = analytics.find_extreme_week(db, "revenue", mode="biggest_increase")
    assert jump["week"] == 14


def test_week_summary_bundles_evidence(db):
    summary = analytics.week_summary(db, 6)
    assert summary["status"] == "ok"
    assert len(summary["dashboard"]) == 11 and "vs_previous_week" in summary["dashboard"][0]
    assert summary["survey"]["top_comments"][0]["comment"] == "Long lines."
    assert set(summary["news"]) == {"Industry News", "Company News"}
    assert analytics.week_summary(db, 99)["status"] == "not_found"


def test_comment_and_news_search(db):
    comments = analytics.search_comments(db, query="expensive", start_week=12)
    assert comments["status"] == "ok" and all("expensive" in c["comment"].lower() for c in comments["comments"])
    news = analytics.search_news(db, query="spring break")
    assert news["count"] == 2 and news["items"][0]["week"] == 9


def test_financial_values_carry_a_month_to_date_note(db):
    cash = analytics.get_financial_line_item(db, "Cash", week=7)
    assert cash["value"] == 69363.92 and "month to date" in cash["note"]
    spend = analytics.account_activity(db, "Adv./Promo.", week=5)
    assert spend["weekly_totals"][0]["payments"] == 700.0
