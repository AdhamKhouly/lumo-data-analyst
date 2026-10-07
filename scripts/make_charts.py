"""Regenerate the README charts from the sanitized data in data/.

    python scripts/make_charts.py            # uses lumo.duckdb if it exists, else loads data/ into memory

Writes three PNGs to assets/. The charts read the same weekly table the modeling code
uses, so they show exactly what Lumo sees.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator, PercentFormatter

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database import DEFAULT_DATA_DIR, DEFAULT_DB_PATH, Database  # noqa: E402
from src.ingest import ingest  # noqa: E402
from src.modeling import WeeklyTable, weekly_table  # noqa: E402

ASSETS = ROOT / "assets"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e2"


def load_table() -> WeeklyTable:
    if DEFAULT_DB_PATH.exists():
        with Database(DEFAULT_DB_PATH, read_only=True) as db:
            return weekly_table(db)
    with Database(":memory:") as db:  # no database yet: parse the workbooks on the fly
        ingest(DEFAULT_DATA_DIR, db)
        return weekly_table(db)


def new_figure(title: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_xlabel("Week", color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    return fig, ax


def line(ax, weeks, values, color, label=None):
    ax.plot(weeks, values, color=color, linewidth=2, marker="o", markersize=4, label=label)


def finish(fig, ax, path: Path, legend: bool) -> None:
    if legend:
        ax.legend(frameon=False, loc="upper left", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def revenue_trend(table: WeeklyTable) -> None:
    weeks, revenue = table.series("revenue")
    fig, ax = new_figure(f"Weekly revenue, {table.company}", "Revenue ($)")
    line(ax, weeks, revenue, BLUE)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v / 1000:,.0f}k"))
    ax.set_ylim(bottom=0)
    ax.annotate(f"${revenue[-1]:,.0f}", (weeks[-1], revenue[-1]), textcoords="offset points",
                xytext=(-6, 8), ha="right", color=INK, fontsize=9)
    finish(fig, ax, ASSETS / "revenue_trend.png", legend=False)


def customer_operations(table: WeeklyTable) -> None:
    # Both series are shares of customers (0 to 1), so they sit on one axis.
    weeks, csat = table.series("customer_satisfaction")
    weeks_w, wait = table.series("wait_time_satisfaction")
    fig, ax = new_figure("Customer satisfaction and wait-time satisfaction", "Share of customers")
    line(ax, weeks, csat, BLUE, "Customer satisfaction (dashboard)")
    line(ax, weeks_w, wait, ORANGE, "Served without a long wait")
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_ylim(0, 1)
    finish(fig, ax, ASSETS / "customer_operations.png", legend=True)


def capacity_demand(table: WeeklyTable) -> None:
    # Capacity, cups served and customers lost are all counts of cups/customers per week.
    weeks, capacity = table.series("weekly_capacity")
    _, served = table.series("cups_served")
    _, lost = table.series("lost_customers")
    fig, ax = new_figure("Capacity, cups served and customers lost", "Cups / customers per week")
    line(ax, weeks, capacity, GREEN, "Weekly capacity")
    line(ax, weeks, served, BLUE, "Cups served")
    line(ax, weeks, lost, ORANGE, "Customers who left or came outside hours")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylim(bottom=0)
    finish(fig, ax, ASSETS / "capacity_demand.png", legend=True)


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    table = load_table()
    revenue_trend(table)
    customer_operations(table)
    capacity_demand(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
