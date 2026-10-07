"""Questions about what happened: look up a metric, compare two weeks, follow a trend,
summarize a week, and search the survey comments and news.

All the arithmetic lives here in plain Python. The language model only decides which of
these functions to call and then explains the result, so the numbers in an answer are
never guessed. Every result is a plain dict so it can be sent to the model as JSON, and
every value carries the file and cell it came from.
"""
from __future__ import annotations

import difflib
from typing import Any

from .database import Database
from .values import format_value

# The metric names people actually use, mapped to where the value lives. Names not listed
# here still work as long as they match a stored metric name exactly.
KNOWN_METRICS: list[tuple[str, str, str, list[str]]] = [
    # (stored name, report_type, section, aliases)
    ("Revenue", "dashboard", "Measures", ["revenue", "sales", "weekly revenue", "total revenue"]),
    ("Weekly Net Income", "dashboard", "Measures", ["net income", "profit", "weekly profit", "earnings"]),
    ("Customer Satisfaction", "dashboard", "Measures", ["customer satisfaction", "satisfaction", "csat"]),
    ("Wait Time Satisfaction", "dashboard", "Measures", ["wait time satisfaction", "wait satisfaction", "wait time"]),
    ("Revenue per Employee", "dashboard", "Measures", ["revenue per employee", "productivity"]),
    ("Cup Sales", "dashboard", "Measures", ["cup sales", "cups sold", "cups"]),
    ("Share of Revenue", "dashboard", "Measures", ["share of revenue", "market share"]),
    ("Gross Margin", "dashboard", "Measures", ["gross margin", "margin"]),
    ("Weekly Change in Cash", "dashboard", "Measures", ["change in cash", "cash change"]),
    ("Capacity Utilization", "dashboard", "Measures", ["capacity utilization", "utilization"]),
    ("Weekly Purchase Variance", "dashboard", "Measures", ["purchase variance"]),
    ("Cups Served", "receipts", "Weekly Traffic Totals", ["cups served", "customers served"]),
    ("Daily Capacity", "receipts", "Weekly Traffic Totals", ["capacity", "weekly capacity"]),
    ("Long Wait", "receipts", "Weekly Traffic Totals", ["long wait", "long waits", "customers who waited"]),
    ("Left or Outside Hours", "receipts", "Weekly Traffic Totals",
     ["lost customers", "customers who left", "customers lost", "walkaways", "left or outside hours"]),
    ("Avg. Price", "receipts", "Weekly Traffic Totals", ["average price", "avg price", "price per cup"]),
    ("Price Rating", "survey", "Survey Category Ratings", ["price rating", "price score"]),
    ("Service Rating", "survey", "Survey Category Ratings", ["service rating", "service score"]),
    ("Ambiance Rating", "survey", "Survey Category Ratings", ["ambiance rating", "ambiance score", "ambience"]),
    ("Satisfaction", "survey", "Company Satisfaction", ["survey satisfaction", "industry satisfaction"]),
    ("Employees", "labor", "Employees by Company", ["employees", "headcount", "staff count", "staffing", "staff"]),
    ("Avg. Server Wages", "labor", "Local Labor Market", ["server wages", "market server wage", "local server pay"]),
    ("Avg. Manager Wages", "labor", "Local Labor Market", ["manager wages", "market manager wage"]),
    ("Avg. Turnover Rate", "labor", "Local Labor Market", ["turnover", "turnover rate"]),
    ("Minimum Wage", "labor", "Local Labor Market", ["minimum wage"]),
    ("Adv./Promo. Payments", "checkbook", "Checkbook Account Totals",
     ["advertising", "advertising spend", "marketing spend", "ad spend"]),
    ("Staff Payments", "checkbook", "Checkbook Account Totals", ["staff pay", "staff wages", "payroll"]),
    ("Ending Balance", "checkbook", "Checkbook Balance", ["checkbook balance", "bank balance", "ending balance"]),
    ("Cash", "balance_sheet", "Assets", ["cash", "cash balance"]),
    ("Total Expenses", "income_statement", "Income Statement", ["total expenses", "expenses"]),
]
FINANCIAL_REPORTS = ("income_statement", "balance_sheet", "cash_flow")
MULTI_COMPANY_SECTIONS = ("Company Satisfaction", "Employees by Company")
FINANCIAL_NOTE = ("Financial statement values are cumulative for the period shown (month to date), "
                  "not amounts for the week alone.")


# --------------------------------------------------------------------------- helpers
def _norm(text: str | None) -> str:
    return " ".join(str(text or "").lower().split()).rstrip("?!.")


def resolve_metric(db: Database, name: str, report_type: str | None = None) -> dict[str, Any]:
    """Find which stored metric a name refers to. Returns status ok | ambiguous | not_found."""
    key = _norm(name)
    # Everyday aliases first ("satisfaction" means the dashboard's Customer Satisfaction),
    # then exact stored names.
    matches = [(m, rt, sec) for m, rt, sec, aliases in KNOWN_METRICS
               if key in aliases and (report_type is None or rt == report_type)]
    if not matches:
        matches = [(m, rt, sec) for m, rt, sec, _ in KNOWN_METRICS
                   if key == _norm(m) and (report_type is None or rt == report_type)]
    if not matches:
        sql = "SELECT DISTINCT metric, report_type, section FROM metrics WHERE lower(metric) = ?"
        params: list[Any] = [key]
        if report_type:
            sql += " AND report_type = ?"
            params.append(report_type)
        matches = [(r["metric"], r["report_type"], r["section"]) for r in db.query(sql + " ORDER BY report_type", params)]
    if len(matches) == 1:
        metric, rt, section = matches[0]
        return {"status": "ok", "metric": metric, "report_type": rt, "section": section}
    if len(matches) > 1:
        return {"status": "ambiguous", "query": name, "candidates": [
            {"metric": m, "report_type": rt, "section": sec} for m, rt, sec in matches],
            "message": f"{name!r} exists in several reports; pass report_type to choose"}
    names = sorted({r["metric"] for r in db.query("SELECT DISTINCT metric FROM metrics")})
    aliases = [a for _, _, _, al in KNOWN_METRICS for a in al]
    suggestions = difflib.get_close_matches(key, [n.lower() for n in names] + aliases, n=8, cutoff=0.5)
    return {"status": "not_found", "query": name, "message": f"no metric called {name!r}",
            "suggestions": list(dict.fromkeys(suggestions))[:6]}


def _source(row: dict[str, Any]) -> str:
    return f"{row['source_file']} [{row['sheet_name']}!{row['cell']}]"


def _point(row: dict[str, Any]) -> dict[str, Any]:
    out = {"week": row["week"], "metric": row["metric"], "value": row["value_numeric"],
           "display": format_value(row["value_numeric"], row["unit"], row.get("scale")), "unit": row["unit"],
           "company": row.get("company"), "source": _source(row)}
    if row.get("qualifier"):
        out["qualifier"] = row["qualifier"]  # "about 742" is approximate in the report
    if row.get("rank") is not None:
        out["rank"] = row["rank"]
    if row.get("change_reported") is not None:
        out["change_reported_by_simulation"] = round(row["change_reported"], 4)
    if row.get("report_type") in FINANCIAL_REPORTS:
        out["period"] = row.get("period_label")
        out["note"] = FINANCIAL_NOTE
    return out


def _rows(db: Database, ref: dict[str, Any], week: int | None = None, start_week: int | None = None,
          end_week: int | None = None, company: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM metrics WHERE metric = ? AND report_type = ? AND section = ?"
    params: list[Any] = [ref["metric"], ref["report_type"], ref["section"]]
    if company is None and ref["section"] in MULTI_COMPANY_SECTIONS:
        company = db.company()  # default to our own cafe, not the competitors
    if company is not None:
        sql += " AND lower(company) = ?"
        params.append(company.lower())
    if ref["report_type"] in FINANCIAL_REPORTS:
        sql += " AND period = 'month_to_date'"
    for clause, value in ((" AND week = ?", week), (" AND week >= ?", start_week), (" AND week <= ?", end_week)):
        if value is not None:
            sql += clause
            params.append(value)
    return db.query(sql + " ORDER BY week, line_order", params)


def compute_change(start: float | None, end: float | None, unit: str | None) -> dict[str, Any]:
    """Absolute and relative change between two values. Percent metrics are fractions, so the
    change is also reported in percentage points (40% -> 50% is +10 pp and +25% relative)."""
    if start is None or end is None:
        return {"absolute_change": None, "percent_change": None, "note": "a value is missing"}
    diff = end - start
    out: dict[str, Any] = {
        "absolute_change": round(diff, 4), "absolute_change_display": format_value(diff, unit),
        "percent_change": round(diff / abs(start) * 100, 2) if start else None,
        "direction": "increase" if diff > 0 else "decrease" if diff < 0 else "no change",
    }
    if unit == "percent":
        out["percentage_point_change"] = round(diff * 100, 2)
    if not start:
        out["note"] = "start value is zero, so a percent change is undefined"
    return out


# --------------------------------------------------------------------------- what is available
def list_weeks(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT week, COUNT(*) AS n_files, STRING_AGG(report_type, ', ' ORDER BY report_type) AS reports "
                    "FROM files GROUP BY week ORDER BY week")
    weeks = [r["week"] for r in rows]
    return {"status": "ok" if weeks else "not_found", "company": db.company(), "weeks": weeks,
            "first_week": min(weeks) if weeks else None, "last_week": max(weeks) if weeks else None, "details": rows}


def list_metrics(db: Database, report_type: str | None = None) -> dict[str, Any]:
    sql = ("SELECT report_type, section, metric, MIN(unit) AS unit, COUNT(DISTINCT week) AS n_weeks "
           "FROM metrics WHERE (period IS NULL OR period <> 'year_to_date')")
    params: list[Any] = []
    if report_type:
        sql += " AND report_type = ?"
        params.append(report_type)
    rows = db.query(sql + " GROUP BY ALL ORDER BY report_type, section, metric", params)
    aliases = {m: al for m, rt, _, al in KNOWN_METRICS if report_type is None or rt == report_type}
    return {"status": "ok", "count": len(rows), "metrics": rows, "aliases": aliases}


# --------------------------------------------------------------------------- single values
def get_metric(db: Database, metric: str, week: int, company: str | None = None,
               report_type: str | None = None) -> dict[str, Any]:
    ref = resolve_metric(db, metric, report_type)
    if ref["status"] != "ok":
        return ref
    rows = _rows(db, ref, week=week, company=company)
    if not rows:
        weeks = [r["week"] for r in _rows(db, ref, company=company)]
        return {"status": "not_found", "metric": ref["metric"], "week": week,
                "message": f"no value for {ref['metric']!r} in week {week}", "weeks_with_data": sorted(set(weeks))}
    if len(rows) > 1:
        return {"status": "ambiguous", "metric": ref["metric"], "week": week, "candidates": [_point(r) for r in rows],
                "message": "several values match; pass company to narrow it down"}
    return {"status": "ok", **_point(rows[0])}


# --------------------------------------------------------------------------- comparisons
def compare_metric(db: Database, metric: str, start_week: int, end_week: int, company: str | None = None,
                   report_type: str | None = None) -> dict[str, Any]:
    start = get_metric(db, metric, start_week, company, report_type)
    if start["status"] != "ok":
        return {**start, "message": f"week {start_week}: {start.get('message')}"}
    end = get_metric(db, metric, end_week, company, report_type)
    if end["status"] != "ok":
        return {**end, "message": f"week {end_week}: {end.get('message')}"}
    out = {"status": "ok", "metric": start["metric"], "unit": start["unit"], "start": start, "end": end,
           **compute_change(start["value"], end["value"], start["unit"])}
    if start.get("note"):
        out["note"] = start["note"]
    return out


def metric_trend(db: Database, metric: str, start_week: int | None = None, end_week: int | None = None,
                 company: str | None = None, report_type: str | None = None) -> dict[str, Any]:
    """Every value of a metric over a range of weeks, with week-over-week changes."""
    ref = resolve_metric(db, metric, report_type)
    if ref["status"] != "ok":
        return ref
    rows = _rows(db, ref, start_week=start_week, end_week=end_week, company=company)
    points = [_point(r) for r in rows if r["value_numeric"] is not None]
    if not points:
        return {"status": "not_found", "metric": ref["metric"], "message": "no values in that range"}
    unit = rows[0]["unit"]
    for prev, cur in zip(points, points[1:]):
        cur["change_from_previous_week"] = compute_change(prev["value"], cur["value"], unit)
    values = [p["value"] for p in points]
    lowest, highest = min(points, key=lambda p: p["value"]), max(points, key=lambda p: p["value"])
    out = {"status": "ok", "metric": ref["metric"], "unit": unit, "weeks": [p["week"] for p in points], "points": points,
           "summary": {"first": {"week": points[0]["week"], "display": points[0]["display"]},
                       "last": {"week": points[-1]["week"], "display": points[-1]["display"]},
                       "lowest": {"week": lowest["week"], "display": lowest["display"]},
                       "highest": {"week": highest["week"], "display": highest["display"]},
                       "average": format_value(sum(values) / len(values), unit),
                       "overall_change": compute_change(values[0], values[-1], unit)}}
    if points[0].get("note"):
        out["note"] = points[0]["note"]
    return out


def find_extreme_week(db: Database, metric: str, mode: str = "max", start_week: int | None = None,
                      end_week: int | None = None, company: str | None = None) -> dict[str, Any]:
    """Week with the highest/lowest value, or the biggest week-over-week rise/drop."""
    modes = ("max", "min", "biggest_increase", "biggest_decrease")
    if mode not in modes:
        return {"status": "error", "message": f"mode must be one of {modes}"}
    trend = metric_trend(db, metric, start_week, end_week, company)
    if trend["status"] != "ok":
        return trend
    points = trend["points"]
    if mode in ("max", "min"):
        best = (max if mode == "max" else min)(points, key=lambda p: p["value"])
        ties = [p["week"] for p in points if p["value"] == best["value"] and p["week"] != best["week"]]
        return {"status": "ok", "metric": trend["metric"], "mode": mode, "week": best["week"], "value": best["value"],
                "display": best["display"], "tied_weeks": ties, "weeks_considered": trend["weeks"], "source": best["source"]}
    candidates = [p for p in points if p.get("change_from_previous_week", {}).get("absolute_change") is not None]
    if not candidates:
        return {"status": "not_found", "message": "need at least two consecutive weeks of data"}
    pick = max if mode == "biggest_increase" else min
    best = pick(candidates, key=lambda p: p["change_from_previous_week"]["absolute_change"])
    return {"status": "ok", "metric": trend["metric"], "mode": mode, "week": best["week"],
            "change": best["change_from_previous_week"], "value": best["display"], "weeks_considered": trend["weeks"]}


def compare_weeks(db: Database, week_a: int, week_b: int) -> dict[str, Any]:
    """Side-by-side change in every dashboard, survey and traffic metric between two weeks."""
    rows = db.query(
        "SELECT * FROM metrics WHERE week IN (?, ?) AND ("
        "(report_type = 'dashboard') OR (report_type = 'survey' AND (company = ? OR company IS NULL)) "
        "OR (report_type = 'receipts' AND section = 'Weekly Traffic Totals') "
        "OR (report_type = 'labor' AND company = ?)) ORDER BY report_type, line_order",
        [week_a, week_b, db.company(), db.company()])
    by_metric: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for r in rows:
        by_metric.setdefault((r["report_type"], r["metric"]), {})[r["week"]] = r
    comparisons = []
    for (report_type, metric), weeks in by_metric.items():
        a, b = weeks.get(week_a), weeks.get(week_b)
        if a and b:
            comparisons.append({"metric": metric, "report_type": report_type,
                                f"week_{week_a}": _point(a)["display"], f"week_{week_b}": _point(b)["display"],
                                **compute_change(a["value_numeric"], b["value_numeric"], a["unit"])})
    if not comparisons:
        return {"status": "not_found", "message": f"no data to compare for weeks {week_a} and {week_b}"}
    return {"status": "ok", "week_a": week_a, "week_b": week_b, "comparisons": comparisons}


# --------------------------------------------------------------------------- one week at a glance
def week_summary(db: Database, week: int, top_comments: int = 8) -> dict[str, Any]:
    """Everything worth knowing about one week, for 'what happened' and 'why' questions."""
    if week not in db.weeks():
        return {"status": "not_found", "week": week, "message": f"week {week} is not in the database", "weeks": db.weeks()}
    company = db.company()
    dashboard = []
    previous = {r["metric"]: r for r in db.query(
        "SELECT * FROM metrics WHERE week = ? AND report_type = 'dashboard'", [week - 1])}
    for r in db.query("SELECT * FROM metrics WHERE week = ? AND report_type = 'dashboard' ORDER BY line_order", [week]):
        point = _point(r)
        if r["metric"] in previous:
            point["vs_previous_week"] = compute_change(previous[r["metric"]]["value_numeric"], r["value_numeric"], r["unit"])
        dashboard.append(point)
    survey = {
        "satisfaction": [_point(r) for r in db.query(
            "SELECT * FROM metrics WHERE week = ? AND section = 'Company Satisfaction' ORDER BY line_order", [week])],
        "ratings": [_point(r) for r in db.query(
            "SELECT * FROM metrics WHERE week = ? AND section = 'Survey Category Ratings' ORDER BY line_order", [week])],
        "top_comments": db.query("SELECT comment, weight FROM survey_comments WHERE week = ? "
                                 "ORDER BY weight DESC, comment_order LIMIT ?", [week, top_comments]),
    }
    news: dict[str, list[str]] = {}
    for r in db.query("SELECT section, text FROM text_records WHERE week = ? ORDER BY section, text_order", [week]):
        news.setdefault(r["section"], []).append(r["text"])
    traffic = [_point(r) for r in db.query(
        "SELECT * FROM metrics WHERE week = ? AND section = 'Weekly Traffic Totals' ORDER BY line_order", [week])]
    products = [_point(r) for r in db.query(
        "SELECT * FROM metrics WHERE week = ? AND section = 'Product Sales' ORDER BY line_order", [week])]
    labor = {
        "market": [_point(r) for r in db.query(
            "SELECT * FROM metrics WHERE week = ? AND section = 'Local Labor Market' ORDER BY line_order", [week])],
        "employees_by_company": db.query(
            "SELECT company, value_numeric AS employees FROM metrics WHERE week = ? AND section = 'Employees by Company' "
            "ORDER BY value_numeric DESC", [week]),
    }
    checkbook = db.query("SELECT metric, value_numeric AS amount FROM metrics WHERE week = ? AND report_type = 'checkbook' "
                         "ORDER BY line_order", [week])
    financial = [_point(r) for r in db.query(
        "SELECT * FROM metrics WHERE week = ? AND period = 'month_to_date' AND ("
        "(report_type = 'income_statement' AND metric IN ('Revenue', 'COGS', 'Total Expenses', 'Net Income')) OR "
        "(report_type = 'balance_sheet' AND metric IN ('Cash', 'Total Assets', 'Total Liabilities', 'Retained Earnings')))"
        " ORDER BY report_type, line_order", [week])]
    decisions = db.query("SELECT decision_week, section, item, value_text FROM decisions WHERE week = ? "
                         "ORDER BY decision_week, cell", [week])
    return {"status": "ok", "week": week, "company": company, "dashboard": dashboard, "survey": survey, "news": news,
            "traffic": traffic, "product_sales": products, "labor": labor, "checkbook_totals": checkbook,
            "financial_statements": {"note": FINANCIAL_NOTE, "items": financial}, "decisions": decisions,
            "caveat": "These are things that happened in the same week. Moving together does not prove cause."}


# --------------------------------------------------------------------------- text
def _keyword_filter(column: str, query: str | None) -> tuple[str, list[str]]:
    words = [w for w in _norm(query).split() if w] if query else []
    return "".join(f" AND lower({column}) LIKE ?" for _ in words), [f"%{w}%" for w in words]


def search_comments(db: Database, query: str | None = None, week: int | None = None, start_week: int | None = None,
                    end_week: int | None = None, min_weight: float | None = None, limit: int = 25) -> dict[str, Any]:
    """Customer survey comments, optionally filtered by keyword and week. Weight = how much the
    comment counted in the survey (higher means more customers said it)."""
    sql = "SELECT week, comment, weight, source_file, cell FROM survey_comments WHERE 1 = 1"
    params: list[Any] = []
    for clause, value in ((" AND week = ?", week), (" AND week >= ?", start_week), (" AND week <= ?", end_week),
                          (" AND weight >= ?", min_weight)):
        if value is not None:
            sql += clause
            params.append(value)
    clause, words = _keyword_filter("comment", query)
    rows = db.query(sql + clause + " ORDER BY week, weight DESC LIMIT ?", params + words + [int(limit)])
    if not rows:
        return {"status": "not_found", "query": query, "week": week, "message": "no survey comments match"}
    return {"status": "ok", "query": query, "count": len(rows), "weeks": sorted({r["week"] for r in rows}),
            "comments": rows, "note": "weight is the survey's importance weight for the comment"}


def search_news(db: Database, query: str | None = None, week: int | None = None, section: str | None = None,
                limit: int = 30) -> dict[str, Any]:
    """Industry news and company news from the dashboard, by keyword and/or week."""
    sql = "SELECT week, section, text, source_file, cell FROM text_records WHERE 1 = 1"
    params: list[Any] = []
    if week is not None:
        sql += " AND week = ?"
        params.append(week)
    if section:
        sql += " AND lower(section) = ?"
        params.append(section.lower())
    clause, words = _keyword_filter("text", query)
    rows = db.query(sql + clause + " ORDER BY week, section, text_order LIMIT ?", params + words + [int(limit)])
    if not rows:
        return {"status": "not_found", "query": query, "week": week, "message": "no news items match"}
    return {"status": "ok", "query": query, "count": len(rows), "items": rows}


# --------------------------------------------------------------------------- money
def get_financial_line_item(db: Database, item: str, week: int | None = None, statement: str | None = None) -> dict[str, Any]:
    """A line from the income statement, balance sheet or cash flow statement (month to date)."""
    sql = ("SELECT * FROM metrics WHERE report_type IN ('income_statement', 'balance_sheet', 'cash_flow') "
           "AND lower(metric) = ? AND period = 'month_to_date'")
    params: list[Any] = [_norm(item)]
    if statement:
        sql += " AND report_type = ?"
        params.append(statement)
    if week is not None:
        sql += " AND week = ?"
        params.append(week)
    rows = db.query(sql + " ORDER BY report_type, week", params)
    if not rows:
        names = sorted({r["metric"] for r in db.query(
            "SELECT DISTINCT metric FROM metrics WHERE report_type IN ('income_statement', 'balance_sheet', 'cash_flow')")})
        return {"status": "not_found", "item": item, "message": f"no financial line item called {item!r}",
                "suggestions": difflib.get_close_matches(item, names, n=6, cutoff=0.4)}
    statements = {r["report_type"] for r in rows}
    if len(statements) > 1:
        return {"status": "ambiguous", "item": item, "statements": sorted(statements),
                "message": "this line exists in several statements; pass statement="}
    points = [_point(r) for r in rows]
    return {"status": "ok", "item": rows[0]["metric"], "statement": rows[0]["report_type"], "note": FINANCIAL_NOTE,
            **({"week": week, **points[0]} if week is not None and len(points) == 1 else {"points": points})}


def account_activity(db: Database, account: str, week: int | None = None) -> dict[str, Any]:
    """Actual checkbook payments and deposits for one account (e.g. 'Adv./Promo.', 'Staff', 'COGS')."""
    accounts = [r["account"] for r in db.query("SELECT DISTINCT account FROM transactions WHERE account IS NOT NULL")]
    match = [a for a in accounts if _norm(a) == _norm(account)] or [a for a in accounts if _norm(account) in _norm(a)]
    if len(match) != 1:
        return {"status": "not_found" if not match else "ambiguous", "account": account,
                "available_accounts": sorted(accounts), "candidates": match}
    sql = ("SELECT week, SUM(COALESCE(payment, 0)) AS payments, SUM(COALESCE(deposit, 0)) AS deposits, "
           "COUNT(*) AS n_transactions FROM transactions WHERE account = ?")
    params: list[Any] = [match[0]]
    if week is not None:
        sql += " AND week = ?"
        params.append(week)
    totals = db.query(sql + " GROUP BY week ORDER BY week", params)
    transactions = db.query("SELECT week, date_text, description, payment, deposit FROM transactions WHERE account = ?"
                            + (" AND week = ?" if week is not None else "") + " ORDER BY week, txn_order", params)
    return {"status": "ok", "account": match[0], "week": week, "weekly_totals": totals, "transactions": transactions,
            "note": "payments are money out, deposits are money in, for that week's checkbook"}


def get_decisions(db: Database, week: int | None = None) -> dict[str, Any]:
    """The decision summary (purchases, staffing, prices, marketing), where the simulation provided one."""
    sql = "SELECT decision_week, section, item, value_text, value_numeric, source_file FROM decisions"
    params: list[Any] = []
    if week is not None:
        sql += " WHERE decision_week = ?"
        params.append(week)
    rows = db.query(sql + " ORDER BY decision_week, cell", params)
    if not rows:
        weeks = [r["decision_week"] for r in db.query("SELECT DISTINCT decision_week FROM decisions ORDER BY 1")]
        return {"status": "not_found", "week": week, "message": "no decision summary for that week",
                "weeks_with_decisions": weeks}
    return {"status": "ok", "week": week, "count": len(rows), "decisions": rows}
