import pytest

from src.parsers import parse_report, report_type_for
from tests.conftest import DATA_DIR, requires_data

pytestmark = requires_data


def parse(week: int, name: str):
    return parse_report(DATA_DIR / f"Week {week}" / name, week, f"Week {week}/{name}")


def metric(report, name, **match):
    rows = [m for m in report.metrics if m["metric"] == name and all(m.get(k) == v for k, v in match.items())]
    assert rows, f"{name} not found"
    return rows[0]


def test_dashboard_measures_news_and_title():
    r = parse(7, "results-dashboard.xlsx")
    assert r.company == "Cafe A"
    revenue = metric(r, "Revenue")
    assert (revenue["value_numeric"], revenue["unit"], revenue["rank"]) == (26528.49, "USD", 4)
    assert revenue["cell"] == "B5" and revenue["sheet_name"] == "Dashboard"
    assert metric(r, "Customer Satisfaction")["value_numeric"] == pytest.approx(0.63)
    sections = {t["section"] for t in r.text_records}
    assert sections == {"Industry News", "Company News"}


def test_survey_satisfaction_ratings_and_comments():
    r = parse(1, "market-survey.xlsx")
    ours = metric(r, "Satisfaction", company="Cafe A")
    assert ours["value_numeric"] == pytest.approx(0.403113)
    assert metric(r, "Satisfaction", company="Industry Average")["unit"] == "percent"
    assert metric(r, "Service Rating")["value_numeric"] == 1.0
    assert metric(r, "Service Rating")["scale"] == 5.0
    assert len(r.comments) == 15
    assert r.comments[0] == {**r.comments[0], "comment": "Long lines.", "weight": 5.0}


def test_labor_market_rates_and_employees():
    r = parse(1, "market-labor.xlsx")
    wages = metric(r, "Avg. Manager Wages")
    assert (wages["value_numeric"], wages["period"]) == (931.25, "per week")
    assert metric(r, "Avg. Turnover Rate")["value_numeric"] == pytest.approx(0.139)
    assert metric(r, "Employees", company="Cafe A")["value_numeric"] == 11
    assert metric(r, "Employees", company="10")["value_numeric"] == 2  # unused slots are numbered


def test_receipts_daily_rows_totals_and_products():
    r = parse(7, "results-receipts.xlsx")
    days = [d for d in r.daily_receipts if not d["is_total"]]
    assert len(days) == 7 and days[0]["day"] == "Monday" and days[0]["cups_served"] == 596
    assert metric(r, "Cups Served")["value_numeric"] == 3979
    left = metric(r, "Left or Outside Hours")
    assert (left["value_numeric"], left["qualifier"], left["value_text"]) == (742.0, "about", "About 742")
    assert metric(r, "Small Coffee Units")["value_numeric"] == 1546
    assert metric(r, "Total Receipts")["value_numeric"] == 26528.49


def test_checkbook_transactions_and_derived_totals():
    r = parse(7, "results-checkbook.xlsx")
    assert len(r.transactions) == 14
    assert r.transactions[0]["description"] == "112 pounds Bulk Coffee"
    assert metric(r, "Ending Balance")["value_numeric"] == 69363.92
    assert metric(r, "Adv./Promo. Payments")["value_numeric"] == 700.0
    assert metric(r, "Revenue Deposits")["value_numeric"] == pytest.approx(26528.49)


def test_financial_statements_keep_their_period():
    income = parse(7, "results-income_statement.xlsx")
    assert metric(income, "Revenue", period="month_to_date")["value_numeric"] == pytest.approx(65285.04)
    assert metric(income, "Revenue", period="year_to_date")["value_numeric"] == pytest.approx(119139.34)
    assert metric(income, "Net Income", period="month_to_date")["period_label"] == "February, Month to Date"
    balance = parse(7, "results-balance_sheet.xlsx")
    assert metric(balance, "Cash", section="Assets")["value_numeric"] == 69363.92
    cash_flow = parse(7, "results-cash_flow.xlsx")
    assert metric(cash_flow, "Net Cash From Operations")["section"] == "Cash Flow From Operations"


def test_decision_summary_has_one_column_per_week():
    r = parse(9, "decisions-review.xlsx")
    servers = {d["decision_week"]: d["value_numeric"] for d in r.decisions
               if d["section"] == "Servers" and d["item"] == "Employed"}
    assert servers == {9: 24.0, 10: 28.0}


def test_report_type_detection():
    assert report_type_for("results-dashboard.xlsx") == "dashboard"
    assert report_type_for("market-survey.xlsx") == "survey"
    assert report_type_for("notes.xlsx") is None
