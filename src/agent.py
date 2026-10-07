"""Lumo: the conversational layer.

How a question gets answered:

    question -> Claude picks one or more tools -> Python runs them against DuckDB
             -> the results go back to Claude -> Claude writes the answer

Claude never sees the spreadsheets and never does the arithmetic. It only chooses which
function to call (from the TOOLS list below) and explains what the function returned. If
a tool says the data is not there, the answer says so.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from . import analytics, modeling, planning
from .database import Database

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 10

INT, STR, NUM = {"type": "integer"}, {"type": "string"}, {"type": "number"}
OPT_INT, OPT_STR, OPT_NUM = {"type": ["integer", "null"]}, {"type": ["string", "null"]}, {"type": ["number", "null"]}


def _tool(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties or {}, "required": required or []}}


TOOLS: list[dict[str, Any]] = [
    _tool("list_weeks", "Which weeks are loaded and which reports each week has."),
    _tool("list_metrics", "Every stored metric name grouped by report, plus the everyday aliases that work.",
          {"report_type": OPT_STR}),
    _tool("get_metric", "One metric for one week, with its unit, rank and source cell. Aliases work ('sales', 'profit', 'csat').",
          {"metric": STR, "week": INT, "company": OPT_STR, "report_type": OPT_STR}, ["metric", "week"]),
    _tool("compare_metric", "Change in one metric between two weeks: absolute, percent, and percentage points for rates.",
          {"metric": STR, "start_week": INT, "end_week": INT, "company": OPT_STR, "report_type": OPT_STR},
          ["metric", "start_week", "end_week"]),
    _tool("metric_trend", "A metric across a range of weeks with week-over-week changes and a summary.",
          {"metric": STR, "start_week": OPT_INT, "end_week": OPT_INT, "company": OPT_STR}, ["metric"]),
    _tool("find_extreme_week", "Week with the highest/lowest value of a metric, or the biggest weekly rise/drop "
          "(mode: max, min, biggest_increase, biggest_decrease).",
          {"metric": STR, "mode": STR, "start_week": OPT_INT, "end_week": OPT_INT}, ["metric"]),
    _tool("week_summary", "Everything about one week: dashboard with changes vs the previous week, survey ratings and "
          "top comments, news, traffic, labor, checkbook totals, financial highlights. Use for 'what happened' and 'why'.",
          {"week": INT}, ["week"]),
    _tool("compare_weeks", "Side-by-side change in every main metric between two weeks.",
          {"week_a": INT, "week_b": INT}, ["week_a", "week_b"]),
    _tool("search_comments", "Customer survey comments with their weights, filtered by keyword and/or week range.",
          {"query": OPT_STR, "week": OPT_INT, "start_week": OPT_INT, "end_week": OPT_INT, "min_weight": OPT_NUM, "limit": OPT_INT}),
    _tool("search_news", "Industry and company news items by keyword and/or week.",
          {"query": OPT_STR, "week": OPT_INT, "section": OPT_STR, "limit": OPT_INT}),
    _tool("get_financial_line_item", "A line from the income statement, balance sheet or cash flow statement "
          "(month-to-date values). Omit week for the whole history.",
          {"item": STR, "week": OPT_INT, "statement": OPT_STR}, ["item"]),
    _tool("account_activity", "Actual checkbook payments and deposits for an account (Adv./Promo., Staff, COGS, ...).",
          {"account": STR, "week": OPT_INT}, ["account"]),
    _tool("get_decisions", "The decision summary (purchases, staffing, prices, marketing) where the simulation provided one.",
          {"week": OPT_INT}),
    _tool("list_variables", "Variables available to the modeling tools (trend, correlations, regression, forecast, scenarios)."),
    _tool("describe_trend", "Direction and size of a variable's movement over the weeks (slope, biggest rise/drop).",
          {"variable": STR, "start_week": OPT_INT, "end_week": OPT_INT}, ["variable"]),
    _tool("correlations", "Which variables moved together with a target variable. Exploratory only.",
          {"target": STR, "start_week": OPT_INT, "end_week": OPT_INT}, ["target"]),
    _tool("fit_regression", "Small OLS regression of a target on one or two predictors, with p-values and caveats.",
          {"target": STR, "predictors": {"type": "array", "items": STR}, "start_week": OPT_INT, "end_week": OPT_INT},
          ["target", "predictors"]),
    _tool("forecast_next_week", "Simple next-week forecast for a variable (recent average and linear trend).",
          {"variable": STR}, ["variable"]),
    _tool("evaluate_scenario", "What if we change staffing, prices, advertising, or demand shifts? changes keys: "
          "employees, extra_employees, price_change_pct, demand_change_pct, advertising_spend. assumptions: elasticity.",
          {"changes": {"type": "object"}, "assumptions": {"type": ["object", "null"]}}, ["changes"]),
    _tool("compare_scenarios", "Run several scenarios ({name, changes}) and rank them on an objective "
          "(net_income, revenue, cups_served, customer_satisfaction).",
          {"scenarios": {"type": "array", "items": {"type": "object"}}, "objective": OPT_STR,
           "assumptions": {"type": ["object", "null"]}}, ["scenarios"]),
    _tool("plan_next_week", "Evidence for a next-week recommendation: latest situation, warning signals, demand forecast, "
          "and a ranking of candidate moves on an objective (net_income, revenue, cups_served, customer_satisfaction).",
          {"objective": OPT_STR, "assumptions": {"type": ["object", "null"]}}),
]


def run_tool(db: Database, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call one analytics/modeling function by name. Returns a JSON-friendly dict."""
    args = {k: v for k, v in (arguments or {}).items() if v is not None}
    functions: dict[str, Callable[..., dict[str, Any]]] = {
        "list_weeks": lambda: analytics.list_weeks(db),
        "list_metrics": lambda: analytics.list_metrics(db, **args),
        "get_metric": lambda: analytics.get_metric(db, **args),
        "compare_metric": lambda: analytics.compare_metric(db, **args),
        "metric_trend": lambda: analytics.metric_trend(db, **args),
        "find_extreme_week": lambda: analytics.find_extreme_week(db, **args),
        "week_summary": lambda: analytics.week_summary(db, **args),
        "compare_weeks": lambda: analytics.compare_weeks(db, **args),
        "search_comments": lambda: analytics.search_comments(db, **args),
        "search_news": lambda: analytics.search_news(db, **args),
        "get_financial_line_item": lambda: analytics.get_financial_line_item(db, **args),
        "account_activity": lambda: analytics.account_activity(db, **args),
        "get_decisions": lambda: analytics.get_decisions(db, **args),
        "list_variables": lambda: modeling.list_variables(modeling.weekly_table(db)),
        "describe_trend": lambda: modeling.describe_trend(modeling.weekly_table(db), **args),
        "correlations": lambda: modeling.correlations(modeling.weekly_table(db), **args),
        "fit_regression": lambda: modeling.fit_regression(modeling.weekly_table(db), **args),
        "forecast_next_week": lambda: modeling.forecast_next_week(modeling.weekly_table(db), **args),
        "evaluate_scenario": lambda: planning.evaluate_scenario(modeling.weekly_table(db), **args),
        "compare_scenarios": lambda: planning.compare_scenarios(modeling.weekly_table(db), **args),
        "plan_next_week": lambda: planning.plan_next_week(db, modeling.weekly_table(db), **args),
    }
    if name not in functions:
        return {"status": "error", "message": f"unknown tool {name!r}"}
    try:
        return to_jsonable(functions[name]())
    except TypeError as exc:
        return {"status": "error", "message": f"bad arguments for {name}: {exc}"}


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalars
        value = value.item()
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


SYSTEM_PROMPT = """\
You are Lumo, the data analyst for {company}, a cafe in a weekly business simulation. You answer
questions about the weekly reports (dashboard, customer survey, local labor report, daily receipts,
checkbook, income statement, balance sheet, cash flow) using the tools provided.

Rules
- Every number you state must come from a tool result. Never calculate, estimate or remember a
  number yourself; call the tool again if you need it.
- If a tool returns status not_found or ambiguous, say what is missing and pass on its suggestions.
  Never fill a gap with a guess.
- Percentages are stored as fractions (0.403 means 40.3%). Use the `display` strings, and for rate
  metrics keep percentage points apart from relative percent change.
- Income statement, balance sheet and cash flow values are cumulative month-to-date figures, not
  weekly amounts. Say so when you quote them; use account_activity for what was actually paid in a week.
- For "why" questions, gather evidence first (week_summary, search_comments, search_news) and present
  it as evidence: things that happened in the same week, not proof of cause. Say "the data suggests".
- Regression and correlation results are associations in about a dozen weeks of data. Say that
  plainly, and never claim one thing caused another from them.
- Scenario and planning results depend on the assumptions the tool lists. Quote the key assumption
  and the warnings when you use them, and give ranges or rough figures rather than false precision.

Choosing tools
- one metric, one week: get_metric. Two weeks: compare_metric. Over time: metric_trend.
- best/worst week or biggest jump: find_extreme_week. Two whole weeks: compare_weeks.
- "what happened in week N" or "why did X change": week_summary first, then comments/news if useful.
- "what drives X", "is X related to Y": correlations, then fit_regression for one or two predictors.
- "what if we ...": evaluate_scenario or compare_scenarios. "what should we do next week": plan_next_week.
- unsure a metric exists: list_metrics or list_variables.

Answer like a colleague who knows the business: lead with the answer, give figures with units and the
weeks they belong to, and keep simple lookups to a sentence or two. Mention the source file only when
asked or when it matters.
{coverage}
"""


@dataclass
class Conversation:
    """The message history for one chat. Each Discord user or channel gets its own."""
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user" and isinstance(m["content"], str))

    def clear(self) -> None:
        self.messages.clear()


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    status: str


@dataclass
class Answer:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None


class Lumo:
    def __init__(self, db: Database, model: str | None = None, client: Any | None = None) -> None:
        self.db = db
        self.model = model or os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
        if client is None:
            import anthropic  # imported here so the analytics work without the SDK installed
            client = anthropic.Anthropic()
        self.client = client

    def system_prompt(self) -> str:
        weeks = self.db.weeks()
        coverage = (f"\nThe database currently holds weeks {min(weeks)} to {max(weeks)} ({len(weeks)} weeks)."
                    if weeks else "\nThe database is empty.")
        return SYSTEM_PROMPT.format(company=self.db.company() or "the cafe", coverage=coverage)

    def ask(self, question: str, conversation: Conversation | None = None) -> Answer:
        """Answer one question, calling tools as many times as Claude needs (up to a limit)."""
        conversation = conversation if conversation is not None else Conversation()
        conversation.messages.append({"role": "user", "content": question})
        calls: list[ToolCall] = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.model, max_tokens=8000, system=self.system_prompt(),
                tools=TOOLS, messages=conversation.messages,
            )
            conversation.messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break
            results = []
            for block in tool_uses:
                result = run_tool(self.db, block.name, dict(block.input))
                calls.append(ToolCall(block.name, dict(block.input), str(result.get("status"))))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                                "is_error": result.get("status") == "error"})
            conversation.messages.append({"role": "user", "content": results})
        else:
            return Answer("I ran out of steps while working on that. Could you ask a narrower question?", calls,
                          error="too_many_tool_rounds")
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "refusal":
            return Answer("I can't help with that one.", calls, error="refusal")
        return Answer(text or "I could not find anything to say about that.", calls)
