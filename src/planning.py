"""Thinking about next week: what-if scenarios and a next-week planning summary.

The scenario model is deliberately small enough to read in one go:

    capacity   = capacity per employee (latest week) x employees
    demand     = latest demand x (1 + demand change) x (1 + price change) ^ elasticity
    lost share = latest lost share + slope x (change in demand/capacity)   <- fitted on past weeks
    served     = demand x (1 - lost share)
    revenue    = served x (price per cup + other sales per cup)
    net change = revenue change - cost of goods change - payroll change - advertising change

Everything that cannot be measured from the reports (above all, how demand reacts to
price) is an explicit assumption that the caller can override, and the result lists every
assumption it used. The planner does not decide anything: it gathers the evidence and
ranks a few candidate scenarios, and Lumo writes the recommendation from that.
"""
from __future__ import annotations

from typing import Any

from .database import Database
from .modeling import WeeklyTable, describe_trend, fit_regression, forecast_next_week

DEFAULT_ELASTICITY = -0.7   # % change in demand per 1% change in price (assumed, not measured)
OBJECTIVES = ("net_income", "revenue", "cups_served", "customer_satisfaction")
COMPLAINT_TOPICS = {"waits": ("line", "wait", "slow", "hurry"), "price": ("expensive", "price", "pricey"),
                    "service": ("service", "staff", "rude"), "coffee quality": ("terrible", "bitter", "weak")}


def _need(table: WeeklyTable, names: list[str]) -> dict[str, float]:
    missing = [n for n in names if table.value(n) is None]
    if missing:
        raise ValueError(f"latest week {table.latest_week} is missing {missing}")
    return {n: table.value(n) for n in names}


def _fitted_slope(table: WeeklyTable, target: str, expected_sign: int) -> dict[str, Any] | None:
    """Slope of `target` against demand/capacity from the weeks so far, if it has the expected sign."""
    fit = fit_regression(table, target, ["demand_to_capacity"])
    if fit["status"] != "ok" or fit["coefficients"][0]["coefficient"] * expected_sign <= 0:
        return None
    return {"slope": fit["coefficients"][0]["coefficient"], "r_squared": fit["r_squared"], "n_weeks": fit["n_weeks"]}


def _lost_customer_model(table: WeeklyTable) -> dict[str, Any] | None:
    """Customers walk away even in weeks with spare capacity overall, because the busy days and
    hours fill up first. So instead of capping served cups at capacity, the share of customers
    lost is modelled as rising with demand/capacity, at the rate seen in past weeks."""
    return _fitted_slope(table, "lost_share", expected_sign=+1)


def _wait_satisfaction_model(table: WeeklyTable) -> dict[str, Any] | None:
    """Wait-time satisfaction vs demand/capacity, estimated from the weeks so far."""
    return _fitted_slope(table, "wait_time_satisfaction", expected_sign=-1)


def evaluate_scenario(table: WeeklyTable, changes: dict[str, Any] | None = None,
                      assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimate next week if we change staffing, prices, advertising or if demand shifts.

    changes:     employees (absolute) or extra_employees (+/-), price_change_pct,
                 demand_change_pct, advertising_spend
    assumptions: elasticity (default -0.7)
    """
    changes = dict(changes or {})
    assumptions = dict(assumptions or {})
    unknown = set(changes) - {"employees", "extra_employees", "price_change_pct", "demand_change_pct", "advertising_spend"}
    if unknown:
        return {"status": "error", "message": f"unknown change(s) {sorted(unknown)}"}
    try:
        base = _need(table, ["employees", "weekly_capacity", "demand", "demand_to_capacity", "lost_share",
                             "cups_served", "revenue", "avg_price", "gross_margin", "net_income"])
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    payroll = table.value("payroll") or 0.0
    advertising = table.value("advertising_spend") or 0.0
    elasticity = float(assumptions.get("elasticity", DEFAULT_ELASTICITY))

    employees = float(changes.get("employees", base["employees"] + float(changes.get("extra_employees", 0))))
    price_change = float(changes.get("price_change_pct", 0)) / 100
    demand_change = float(changes.get("demand_change_pct", 0)) / 100
    new_advertising = float(changes.get("advertising_spend", advertising))
    if employees < 1:
        return {"status": "error", "message": "employees must be at least 1"}

    capacity_per_employee = base["weekly_capacity"] / base["employees"]
    lost_model = _lost_customer_model(table)
    other_per_cup = max(base["revenue"] / base["cups_served"] - base["avg_price"], 0.0)  # baked goods etc.
    payroll_per_employee = payroll / base["employees"]

    def simulate(emp: float, price_pct: float, demand_pct: float, ads: float) -> dict[str, float]:
        capacity = capacity_per_employee * emp
        demand = base["demand"] * (1 + demand_pct) * (1 + price_pct) ** elasticity
        load = demand / capacity
        lost_share = base["lost_share"] + (lost_model["slope"] * (load - base["demand_to_capacity"]) if lost_model else 0.0)
        served = demand * (1 - min(max(lost_share, 0.0), 1.0))
        revenue = served * (base["avg_price"] * (1 + price_pct) + other_per_cup)
        cogs = revenue * (1 - base["gross_margin"])
        return {"employees": emp, "weekly_capacity": capacity, "demand": demand, "cups_served": served,
                "lost_customers": demand - served, "capacity_utilization": served / capacity if capacity else 0.0,
                "demand_to_capacity": demand / capacity if capacity else 0.0, "revenue": revenue, "cogs": cogs,
                "payroll": payroll_per_employee * emp, "advertising_spend": ads,
                "net_income_change": 0.0}

    baseline = simulate(base["employees"], 0.0, 0.0, advertising)
    scenario = simulate(employees, price_change, demand_change, new_advertising)
    for s in (baseline, scenario):
        s["net_income_change"] = ((s["revenue"] - baseline["revenue"]) - (s["cogs"] - baseline["cogs"])
                                  - (s["payroll"] - baseline["payroll"]) - (s["advertising_spend"] - baseline["advertising_spend"]))
        s["net_income"] = base["net_income"] + s["net_income_change"]

    wait_model = _wait_satisfaction_model(table)
    wait_latest = table.value("wait_time_satisfaction")
    for s in (baseline, scenario):
        if wait_model and wait_latest is not None:
            s["wait_time_satisfaction"] = min(1.0, max(0.0, wait_latest + wait_model["slope"]
                                                         * (s["demand_to_capacity"] - baseline["demand_to_capacity"])))

    warnings = []
    rng = table.observed_range("employees")
    if rng and not rng["min"] <= employees <= rng["max"]:
        warnings.append(f"{employees:g} employees is outside anything tried so far ({rng['min']:g} to {rng['max']:g}); "
                        "the capacity-per-employee assumption is being stretched.")
    if price_change:
        warnings.append(f"The demand response to price (elasticity {elasticity}) is an assumption, not something "
                        "measured from the data. Treat price results as a sensitivity check.")
    if abs(price_change) > 0.10:
        warnings.append("A price move of more than 10% is far from anything tried in the simulation.")
    if new_advertising != advertising:
        warnings.append("Advertising only changes its cost here; its effect on demand cannot be measured from the data.")
    if wait_model is None:
        warnings.append("Wait-time satisfaction is not estimated: no usable relationship with demand/capacity yet.")

    rounded = lambda d: {k: round(v, 3) if k in ("capacity_utilization", "demand_to_capacity", "wait_time_satisfaction")
                         else round(v, 1) for k, v in d.items()}  # noqa: E731
    return {
        "status": "ok", "based_on_week": table.latest_week, "target_week": table.latest_week + 1,
        "changes": changes, "baseline_next_week": rounded(baseline), "scenario_next_week": rounded(scenario),
        "difference_vs_baseline": {k: round(scenario[k] - baseline[k], 3 if k in ("capacity_utilization", "demand_to_capacity",
                                                                               "wait_time_satisfaction") else 1)
                                   for k in scenario if k in baseline},
        "assumptions": [
            f"Capacity per employee stays at {capacity_per_employee:,.0f} cups/week (week {table.latest_week}).",
            (f"The share of customers lost rises {lost_model['slope']:.2f} for each 1.0 rise in demand/capacity, "
             f"starting from week {table.latest_week}'s {base['lost_share']:.0%} (fitted on {lost_model['n_weeks']} weeks, "
             f"R^2 {lost_model['r_squared']})." if lost_model else
             f"The share of customers lost stays at week {table.latest_week}'s {base['lost_share']:.0%}."),
            f"Demand starts from week {table.latest_week} ({base['demand']:,.0f} customers) with no growth unless demand_change_pct is given.",
            f"Price elasticity of demand = {elasticity} (assumed).",
            f"Gross margin stays at {base['gross_margin']:.1%}; payroll is ${payroll_per_employee:,.0f} per employee per week.",
            "Rent, utilities and other fixed costs do not change, so they cancel out in the net income change.",
        ] + ([f"Wait-time satisfaction falls {abs(wait_model['slope']):.2f} per 1.0 rise in demand/capacity "
              f"(fitted on {wait_model['n_weeks']} weeks, R^2 {wait_model['r_squared']})."] if wait_model else []),
        "warnings": warnings,
        "confidence": "low",
    }


def compare_scenarios(table: WeeklyTable, scenarios: list[dict[str, Any]], objective: str = "net_income",
                      assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run several scenarios and rank them on one objective."""
    if objective not in OBJECTIVES:
        return {"status": "error", "message": f"objective must be one of {OBJECTIVES}"}
    rows = []
    for i, s in enumerate(scenarios):
        result = evaluate_scenario(table, s.get("changes", {}), assumptions)
        name = s.get("name") or f"scenario {i + 1}"
        if result["status"] != "ok":
            rows.append({"name": name, "status": "error", "message": result["message"]})
            continue
        key = "wait_time_satisfaction" if objective == "customer_satisfaction" else objective
        value = result["scenario_next_week"].get(key)
        rows.append({"name": name, "status": "ok", "changes": s.get("changes", {}), "objective_value": value,
                     "net_income_change": result["difference_vs_baseline"]["net_income_change"],
                     "revenue": result["scenario_next_week"]["revenue"], "cups_served": result["scenario_next_week"]["cups_served"],
                     "lost_customers": result["scenario_next_week"]["lost_customers"],
                     "capacity_utilization": result["scenario_next_week"]["capacity_utilization"],
                     "warnings": result["warnings"]})
    ok = sorted([r for r in rows if r["status"] == "ok" and r["objective_value"] is not None],
                key=lambda r: -r["objective_value"])
    for rank, r in enumerate(ok, start=1):
        r["rank"] = rank
    note = ("customer satisfaction is approximated by the estimated wait-time satisfaction"
            if objective == "customer_satisfaction" else None)
    return {"status": "ok", "objective": objective, "ranking": ok + [r for r in rows if r["status"] != "ok"],
            "note": note, "confidence": "low"}


# --------------------------------------------------------------------------- next-week planning
def _signals(db: Database, table: WeeklyTable) -> list[dict[str, str]]:
    """Things in the latest week that point at a bottleneck or a problem."""
    w = table.latest_week
    v = lambda name: table.value(name)  # noqa: E731
    signals = []
    if v("capacity_utilization") is not None and v("capacity_utilization") >= 0.85:
        signals.append({"signal": "capacity", "evidence": f"Capacity utilization was {v('capacity_utilization'):.0%} in week {w}."})
    if v("lost_share") is not None and v("lost_share") >= 0.12:
        signals.append({"signal": "capacity", "evidence": f"About {v('lost_share'):.0%} of potential customers "
                                                           f"({v('lost_customers'):,.0f}) left or came outside hours."})
    if v("capacity_utilization") is not None and v("capacity_utilization") < 0.7:
        signals.append({"signal": "demand", "evidence": f"Utilization was only {v('capacity_utilization'):.0%}; there is spare capacity."})
    if v("wait_time_satisfaction") is not None and v("wait_time_satisfaction") < 0.75:
        signals.append({"signal": "waits", "evidence": f"Only {v('wait_time_satisfaction'):.0%} of customers were served without a long wait."})
    if v("price_rating") is not None and v("price_rating") <= 2:
        signals.append({"signal": "price", "evidence": f"The survey price rating was {v('price_rating'):g} out of 5."})
    if v("service_rating") is not None and v("service_rating") <= 2:
        signals.append({"signal": "service", "evidence": f"The survey service rating was {v('service_rating'):g} out of 5."})
    for topic, words in COMPLAINT_TOPICS.items():
        rows = db.query("SELECT comment, weight FROM survey_comments WHERE week = ? ORDER BY weight DESC", [w])
        hits = [r for r in rows if any(word in (r["comment"] or "").lower() for word in words)
                and "okay" not in (r["comment"] or "").lower()]
        if hits and sum(r["weight"] or 0 for r in hits) >= 3:
            signals.append({"signal": topic, "evidence": "Survey comments: " + "; ".join(
                f"\"{r['comment']}\" (weight {r['weight']:g})" for r in hits[:3])})
    for r in db.query("SELECT text FROM text_records WHERE week = ? AND section = 'Company News'", [w]):
        text = r["text"].lower()
        if "quit" in text or "stressed" in text:
            signals.append({"signal": "staffing", "evidence": f"Company news: {r['text']}"})
        if "emergency" in text or "waste" in text:
            signals.append({"signal": "inventory", "evidence": f"Company news: {r['text']}"})
    return signals


def plan_next_week(db: Database, table: WeeklyTable, objective: str = "net_income",
                   assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gather the evidence for a next-week recommendation and rank a few candidate moves."""
    if objective not in OBJECTIVES:
        return {"status": "error", "message": f"objective must be one of {OBJECTIVES}"}
    w = table.latest_week
    situation = {}
    for var in ("revenue", "net_income", "customer_satisfaction", "wait_time_satisfaction", "cups_served",
                "lost_customers", "capacity_utilization", "employees", "avg_price"):
        value, prev = table.value(var), table.value(var, w - 1)
        if value is None:
            continue
        item: dict[str, Any] = {"latest": round(value, 4)}
        if prev is not None:
            item["change_vs_previous_week"] = round(value - prev, 4)
        trend = describe_trend(table, var, start_week=w - 3)
        if trend["status"] == "ok":
            item["trend_last_4_weeks_per_week"] = trend["trend_per_week"]
        situation[var] = item

    employees = table.value("employees") or 0
    candidates = [{"name": "hold current plan", "changes": {}},
                  {"name": "add 1 employee", "changes": {"extra_employees": 1}},
                  {"name": "add 2 employees", "changes": {"extra_employees": 2}},
                  {"name": "add 4 employees", "changes": {"extra_employees": 4}},
                  {"name": "raise prices 5%", "changes": {"price_change_pct": 5}},
                  {"name": "cut prices 5%", "changes": {"price_change_pct": -5}},
                  {"name": "add 2 employees and raise prices 5%", "changes": {"extra_employees": 2, "price_change_pct": 5}}]
    if employees > 1:
        candidates.append({"name": "remove 1 employee", "changes": {"extra_employees": -1}})
    ranking = compare_scenarios(table, candidates, objective, assumptions)
    demand_forecast = forecast_next_week(table, "demand")
    signals = _signals(db, table)

    suggestions = []
    kinds = {s["signal"] for s in signals}
    if "capacity" in kinds or "waits" in kinds:
        suggestions.append("Capacity looks like the main limit: consider adding staff, and check the scenario ranking "
                           "for how many employees the extra revenue would pay for.")
    if "demand" in kinds:
        suggestions.append("There is spare capacity, so the question is demand: advertising or a price change are the "
                           "levers, but their effects are not measurable from this data.")
    if "price" in kinds:
        suggestions.append("Customers rate price poorly; a price increase is risky even if the scenario model likes it.")
    if "service" in kinds:
        suggestions.append("Service is rated poorly; more staff or training may matter more than price.")
    if "staffing" in kinds:
        suggestions.append("Staff are quitting or stressed; compare our pay with the local market before adding more hours.")
    if "inventory" in kinds:
        suggestions.append("Emergency purchases or waste were reported; adjust the coffee order to the demand forecast.")
    if not suggestions:
        suggestions.append("No strong warning signs in the latest week; the ranking below shows which small change "
                           "the model expects to help most.")
    return {"status": "ok", "objective": objective, "based_on_week": w, "target_week": w + 1,
            "situation": situation, "signals": signals, "demand_forecast": demand_forecast.get("suggested"),
            "scenario_ranking": ranking["ranking"], "suggestions": suggestions,
            "caveats": ["Scenario numbers come from the simple model in planning.py with the assumptions it lists.",
                        f"Everything rests on {len(table.weeks)} weeks of data.",
                        "The simulation's own rules (demand, waits, competitors) are not known to the model."],
            "confidence": "low"}
