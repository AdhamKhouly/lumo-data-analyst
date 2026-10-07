"""Simple models on the weekly numbers: trends, correlations, regression and a next-week
forecast.

Everything here works on one table with a row per week and a column per variable, built
from the database on demand (`weekly_table`). The sample is tiny (one row per week of the
simulation), so every function says so and treats its results as exploratory. A
regression here shows an association in a dozen or so weeks; it is not proof that one
thing causes another.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

from .database import Database

MIN_WEEKS_FOR_REGRESSION = 6
MIN_RESIDUAL_DF = 3

# variable name -> (report_type, section, metric, description)
VARIABLES: dict[str, tuple[str, str, str, str]] = {
    "revenue": ("dashboard", "Measures", "Revenue", "weekly revenue ($)"),
    "net_income": ("dashboard", "Measures", "Weekly Net Income", "weekly net income ($)"),
    "gross_margin": ("dashboard", "Measures", "Gross Margin", "gross margin (fraction)"),
    "customer_satisfaction": ("dashboard", "Measures", "Customer Satisfaction", "customer satisfaction (fraction)"),
    "wait_time_satisfaction": ("dashboard", "Measures", "Wait Time Satisfaction", "share of customers served without a long wait"),
    "capacity_utilization": ("dashboard", "Measures", "Capacity Utilization", "cups served / weekly capacity"),
    "revenue_per_employee": ("dashboard", "Measures", "Revenue per Employee", "revenue per employee ($)"),
    "share_of_revenue": ("dashboard", "Measures", "Share of Revenue", "share of all cafes' revenue"),
    "cups_served": ("receipts", "Weekly Traffic Totals", "Cups Served", "cups served in the week"),
    "weekly_capacity": ("receipts", "Weekly Traffic Totals", "Daily Capacity", "total serving capacity for the week (cups)"),
    "long_wait": ("receipts", "Weekly Traffic Totals", "Long Wait", "customers served after a long wait"),
    "lost_customers": ("receipts", "Weekly Traffic Totals", "Left or Outside Hours", "customers who left or came outside hours (approximate)"),
    "avg_price": ("receipts", "Weekly Traffic Totals", "Avg. Price", "average price per cup ($)"),
    "price_rating": ("survey", "Survey Category Ratings", "Price Rating", "survey price rating (out of 5)"),
    "service_rating": ("survey", "Survey Category Ratings", "Service Rating", "survey service rating (out of 5)"),
    "ambiance_rating": ("survey", "Survey Category Ratings", "Ambiance Rating", "survey ambiance rating (out of 5)"),
    "employees": ("labor", "Employees by Company", "Employees", "employees on payroll"),
    "market_server_wage": ("labor", "Local Labor Market", "Avg. Server Wages", "local average server wage ($/hour)"),
    "advertising_spend": ("checkbook", "Checkbook Account Totals", "Adv./Promo. Payments", "advertising paid in the week ($)"),
    "staff_pay": ("checkbook", "Checkbook Account Totals", "Staff Payments", "staff wages paid in the week ($)"),
    "management_pay": ("checkbook", "Checkbook Account Totals", "Management Payments", "manager pay in the week ($)"),
}
DERIVED = {
    "demand": "cups_served + lost_customers (everyone who wanted a coffee)",
    "demand_to_capacity": "demand / weekly_capacity",
    "lost_share": "lost_customers / demand",
    "payroll": "staff_pay + management_pay",
}
ALIASES = {"sales": "revenue", "profit": "net_income", "satisfaction": "customer_satisfaction",
           "csat": "customer_satisfaction", "headcount": "employees", "staff": "employees", "staffing": "employees",
           "capacity": "weekly_capacity", "utilization": "capacity_utilization", "price": "avg_price",
           "average price": "avg_price", "advertising": "advertising_spend", "walkaways": "lost_customers",
           "customers": "cups_served", "wait satisfaction": "wait_time_satisfaction"}


@dataclass
class WeeklyTable:
    weeks: list[int]
    rows: dict[int, dict[str, float]] = field(default_factory=dict)
    company: str | None = None

    @property
    def variables(self) -> list[str]:
        return [v for v in list(VARIABLES) + list(DERIVED) if any(v in r for r in self.rows.values())]

    @property
    def latest_week(self) -> int:
        return max(self.weeks)

    def value(self, name: str, week: int | None = None) -> float | None:
        return self.rows.get(self.latest_week if week is None else week, {}).get(name)

    def series(self, name: str, start_week: int | None = None, end_week: int | None = None) -> tuple[list[int], list[float]]:
        weeks = [w for w in self.weeks if name in self.rows[w]
                 and (start_week is None or w >= start_week) and (end_week is None or w <= end_week)]
        return weeks, [self.rows[w][name] for w in weeks]

    def aligned(self, names: list[str], start_week: int | None = None, end_week: int | None = None) -> tuple[list[int], np.ndarray]:
        """Weeks where every variable is present, and the matrix of their values."""
        weeks = [w for w in self.weeks if all(n in self.rows[w] for n in names)
                 and (start_week is None or w >= start_week) and (end_week is None or w <= end_week)]
        return weeks, np.array([[self.rows[w][n] for n in names] for w in weeks], dtype=float)

    def observed_range(self, name: str) -> dict[str, float] | None:
        _, values = self.series(name)
        return {"min": min(values), "max": max(values)} if values else None


def resolve_variable(name: str) -> str | None:
    key = " ".join(name.lower().replace("_", " ").split())
    for var in list(VARIABLES) + list(DERIVED):
        if key == var.replace("_", " "):
            return var
    return ALIASES.get(key)


def weekly_table(db: Database) -> WeeklyTable:
    """One row per week with every variable the models can use."""
    weeks = db.weeks()
    table = WeeklyTable(weeks=weeks, rows={w: {} for w in weeks}, company=db.company())
    for var, (report_type, section, metric, _) in VARIABLES.items():
        sql = "SELECT week, value_numeric FROM metrics WHERE report_type = ? AND section = ? AND metric = ?"
        params: list[Any] = [report_type, section, metric]
        if section == "Employees by Company":
            sql += " AND company = ?"
            params.append(table.company)
        for r in db.query(sql, params):
            if r["value_numeric"] is not None and r["week"] in table.rows:
                table.rows[r["week"]][var] = float(r["value_numeric"])
    for w, row in table.rows.items():
        if "cups_served" in row and "lost_customers" in row:
            row["demand"] = row["cups_served"] + row["lost_customers"]
            if row["demand"]:
                row["lost_share"] = row["lost_customers"] / row["demand"]
            if row.get("weekly_capacity"):
                row["demand_to_capacity"] = row["demand"] / row["weekly_capacity"]
        if "staff_pay" in row or "management_pay" in row:
            row["payroll"] = row.get("staff_pay", 0.0) + row.get("management_pay", 0.0)
    return table


def list_variables(table: WeeklyTable) -> dict[str, Any]:
    out = []
    for var in table.variables:
        weeks, values = table.series(var)
        description = VARIABLES[var][3] if var in VARIABLES else DERIVED[var]
        out.append({"variable": var, "description": description, "weeks_with_data": len(weeks),
                    "latest": round(values[-1], 4) if values else None})
    return {"status": "ok", "weeks": table.weeks, "variables": out, "aliases": ALIASES}


# --------------------------------------------------------------------------- trends
def linear_fit(x: list[float], y: list[float]) -> tuple[float, float]:
    """Slope and intercept of the least-squares line through (x, y)."""
    slope, intercept = np.polyfit(np.asarray(x, float), np.asarray(y, float), 1)
    return float(slope), float(intercept)


def describe_trend(table: WeeklyTable, variable: str, start_week: int | None = None,
                   end_week: int | None = None) -> dict[str, Any]:
    """How a variable moved over the weeks: direction, average weekly change, biggest moves."""
    var = resolve_variable(variable)
    if var is None:
        return {"status": "not_found", "message": f"unknown variable {variable!r}", "variables": table.variables}
    weeks, values = table.series(var, start_week, end_week)
    if len(values) < 2:
        return {"status": "not_found", "variable": var, "message": "need at least two weeks of data"}
    changes = [b - a for a, b in zip(values, values[1:])]
    slope, _ = linear_fit(weeks, values)
    biggest_up = max(range(len(changes)), key=lambda i: changes[i])
    biggest_down = min(range(len(changes)), key=lambda i: changes[i])
    return {
        "status": "ok", "variable": var, "weeks": weeks, "values": [round(v, 4) for v in values],
        "first": round(values[0], 4), "last": round(values[-1], 4), "min": round(min(values), 4), "max": round(max(values), 4),
        "overall_change": round(values[-1] - values[0], 4),
        "overall_change_pct": round((values[-1] - values[0]) / abs(values[0]) * 100, 1) if values[0] else None,
        "trend_per_week": round(slope, 4), "direction": "up" if slope > 0 else "down" if slope < 0 else "flat",
        "average_weekly_change": round(float(np.mean(changes)), 4),
        "weeks_up": sum(1 for c in changes if c > 0), "weeks_down": sum(1 for c in changes if c < 0),
        "biggest_rise": {"week": weeks[biggest_up + 1], "change": round(changes[biggest_up], 4)},
        "biggest_drop": {"week": weeks[biggest_down + 1], "change": round(changes[biggest_down], 4)},
        "note": "trend_per_week is the slope of a straight line fitted through the weekly values",
    }


# --------------------------------------------------------------------------- correlations
def correlations(table: WeeklyTable, target: str, start_week: int | None = None, end_week: int | None = None) -> dict[str, Any]:
    """Which variables moved together with the target. A first look, not a causal analysis."""
    tgt = resolve_variable(target)
    if tgt is None:
        return {"status": "not_found", "message": f"unknown variable {target!r}", "variables": table.variables}
    results = []
    for var in table.variables:
        if var == tgt:
            continue
        weeks, m = table.aligned([tgt, var], start_week, end_week)
        if len(weeks) < 4 or np.std(m[:, 0]) == 0 or np.std(m[:, 1]) == 0:
            continue
        r, p = stats.pearsonr(m[:, 1], m[:, 0])
        results.append({"variable": var, "r": round(float(r), 3), "p_value": round(float(p), 3), "n_weeks": len(weeks),
                        "strength": "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak"})
    results.sort(key=lambda x: -abs(x["r"]))
    return {"status": "ok", "target": tgt, "correlations": results,
            "caveats": [f"Only {len(table.weeks)} weeks of data, so these correlations are rough.",
                        "Most metrics grew over the simulation, so many pairs correlate just because of time.",
                        "Correlation does not show cause."]}


# --------------------------------------------------------------------------- regression
def fit_regression(table: WeeklyTable, target: str, predictors: list[str], start_week: int | None = None,
                   end_week: int | None = None) -> dict[str, Any]:
    """Ordinary least squares: target = a + b1 * x1 + b2 * x2 + ...

    Refuses to fit when there are too few weeks for the number of predictors, because the
    coefficients would be meaningless. Reports p-values and confidence intervals from the
    t distribution, R squared, and plain-language readings of each coefficient.
    """
    tgt = resolve_variable(target)
    if tgt is None:
        return {"status": "not_found", "message": f"unknown variable {target!r}", "variables": table.variables}
    preds = []
    for p in predictors:
        var = resolve_variable(p)
        if var is None:
            return {"status": "not_found", "message": f"unknown variable {p!r}", "variables": table.variables}
        if var != tgt and var not in preds:
            preds.append(var)
    if not preds:
        return {"status": "error", "message": "give at least one predictor"}
    weeks, m = table.aligned([tgt, *preds], start_week, end_week)
    n, k = len(weeks), len(preds)
    df = n - k - 1
    if n < MIN_WEEKS_FOR_REGRESSION or df < MIN_RESIDUAL_DF:
        return {"status": "insufficient_data", "target": tgt, "predictors": preds, "n_weeks": n,
                "message": f"{n} weeks is too few for {k} predictor(s); need at least "
                           f"{max(MIN_WEEKS_FOR_REGRESSION, k + 1 + MIN_RESIDUAL_DF)}."}
    y, X = m[:, 0], m[:, 1:]
    if any(len(np.unique(np.round(X[:, i], 8))) < 3 for i in range(k)):
        return {"status": "insufficient_data", "target": tgt, "predictors": preds, "n_weeks": n,
                "message": "a predictor barely changed over these weeks, so its effect cannot be estimated"}

    A = np.column_stack([np.ones(n), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    fitted = A @ beta
    residuals = y - fitted
    sse = float(residuals @ residuals)
    sst = float(((y - y.mean()) ** 2).sum())
    sigma2 = sse / df
    cov = sigma2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    t_values = beta / se
    p_values = 2 * stats.t.sf(np.abs(t_values), df)
    t_crit = stats.t.ppf(0.975, df)
    r2 = 1 - sse / sst if sst > 0 else float("nan")

    coefficients = []
    for i, name in enumerate(preds, start=1):
        reading = (f"Across these {n} weeks, one unit more of {name} went together with "
                   f"{beta[i]:+.4g} in {tgt}" + (", holding the other predictors fixed" if k > 1 else "") + ".")
        coefficients.append({"predictor": name, "coefficient": round(float(beta[i]), 6),
                             "std_error": round(float(se[i]), 6), "t": round(float(t_values[i]), 3),
                             "p_value": round(float(p_values[i]), 4),
                             "ci95": [round(float(beta[i] - t_crit * se[i]), 6), round(float(beta[i] + t_crit * se[i]), 6)],
                             "significant_at_5pct": bool(p_values[i] < 0.05), "reading": reading})
    caveats = [f"Only {n} weekly observations. Treat this as exploratory, not as a measured effect.",
               "This is an association in observational data, not evidence that changing the predictor would change the target."]
    week_trend = abs(stats.pearsonr(np.asarray(weeks, float), y)[0]) if n > 2 and np.std(y) > 0 else 0
    if week_trend >= 0.8:
        caveats.append(f"{tgt} rose or fell steadily over time, so anything else that trended will look related to it.")
    return {"status": "ok", "target": tgt, "predictors": preds, "n_weeks": n, "weeks": weeks,
            "intercept": round(float(beta[0]), 6), "coefficients": coefficients,
            "r_squared": round(float(r2), 4), "adjusted_r_squared": round(float(1 - (1 - r2) * (n - 1) / df), 4),
            "residual_std_error": round(float(np.sqrt(sigma2)), 4),
            "fitted": [{"week": w, "actual": round(float(a), 4), "fitted": round(float(f), 4)} for w, a, f in zip(weeks, y, fitted)],
            "caveats": caveats}


# --------------------------------------------------------------------------- forecasting
def forecast_next_week(table: WeeklyTable, variable: str, recent_weeks: int = 6) -> dict[str, Any]:
    """Two simple forecasts for next week: the recent average and a straight-line trend.

    Deliberately basic. With this little history anything fancier would be false precision,
    so the result also reports how far off these methods were in past weeks.
    """
    var = resolve_variable(variable)
    if var is None:
        return {"status": "not_found", "message": f"unknown variable {variable!r}", "variables": table.variables}
    weeks, values = table.series(var)
    if len(values) < 4:
        return {"status": "insufficient_data", "variable": var, "message": "need at least four weeks"}
    recent_w, recent_v = weeks[-recent_weeks:], values[-recent_weeks:]
    slope, intercept = linear_fit(recent_w, recent_v)
    next_week = weeks[-1] + 1
    trend_forecast = slope * next_week + intercept
    average_forecast = float(np.mean(values[-3:]))

    # How wrong would each method have been if we had used it in earlier weeks?
    errors = {"recent_average": [], "linear_trend": []}
    for i in range(3, len(values)):
        actual = values[i]
        errors["recent_average"].append(abs(actual - float(np.mean(values[i - 3:i]))))
        hw, hv = weeks[max(0, i - recent_weeks):i], values[max(0, i - recent_weeks):i]
        if len(hv) >= 2:
            s, c = linear_fit(hw, hv)
            errors["linear_trend"].append(abs(actual - (s * weeks[i] + c)))
    typical_error = {k: round(float(np.mean(v)), 4) if v else None for k, v in errors.items()}
    better = min(typical_error, key=lambda k: typical_error[k] if typical_error[k] is not None else float("inf"))
    point = trend_forecast if better == "linear_trend" else average_forecast
    spread = typical_error[better] or 0.0
    return {"status": "ok", "variable": var, "target_week": next_week, "last_actual": {"week": weeks[-1], "value": round(values[-1], 4)},
            "forecasts": {"recent_average": round(average_forecast, 4), "linear_trend": round(trend_forecast, 4)},
            "typical_past_error": typical_error, "method_with_lower_past_error": better,
            "suggested": {"point": round(point, 4), "low": round(point - spread, 4), "high": round(point + spread, 4),
                          "note": "low/high is the point forecast plus or minus the method's typical past error"},
            "caveats": ["A trend cannot anticipate events like a holiday week or a new decision.",
                        f"Past error is measured on only {len(errors['recent_average'])} weeks."]}
