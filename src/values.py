"""Turn the values found in report cells into numbers with units.

The simulation reports mix real Excel numbers with text that only looks numeric:

    "$5,687"          -> 5687.0   unit USD
    "($3,832)"        -> -3832.0  unit USD (accounting negative)
    "40.3%"           -> 0.403    unit percent (stored as a fraction of 1)
    "1,129"           -> 1129.0   unit count
    "3 out of 5"      -> 3.0      unit rating, scale 5
    "$931.25 / week"  -> 931.25   unit USD, period "per week"
    "About 50"        -> 50.0     unit count, qualifier "about"
    "n/a"             -> None     qualifier "n/a"

Native Excel numbers come with a number format ("$#,##0", "0.0%") which tells us the unit.
Anything we cannot read as a number is kept as text rather than dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

NA_RE = re.compile(r"^(n/?a|none|null|-+)$", re.IGNORECASE)
RATING_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:out of|/|of)\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
QUALIFIER_RE = re.compile(r"^(about|approx\.?|approximately|roughly|more than|over|less than|under|at least|at most)\s+(.+)$",
                          re.IGNORECASE)
RATE_RE = re.compile(r"^(.+?)\s*(?:/|per)\s*(week|hour|month|day|year)$", re.IGNORECASE)
CURRENCY_RE = re.compile(r"^(\()?(-)?\$\s*([\d,]*\.?\d+)(\))?$")
PERCENT_RE = re.compile(r"^(\()?(-)?([\d,]*\.?\d+)\s*%(\))?$")
NUMBER_RE = re.compile(r"^(\()?(-)?([\d,]*\.?\d+)(\))?$")

QUALIFIERS = {
    "about": "about", "approx": "about", "approx.": "about", "approximately": "about", "roughly": "about",
    "more than": "more_than", "over": "more_than", "at least": "at_least",
    "less than": "less_than", "under": "less_than", "at most": "at_most",
}


@dataclass
class ParsedValue:
    numeric: float | None
    text: str
    unit: str | None = None       # USD | percent | count | number | rating
    scale: float | None = None    # for ratings: "3 out of 5" -> 5
    qualifier: str | None = None  # about | more_than | n/a ...
    period: str | None = None     # "per week", "per hour" ...


def unit_from_number_format(number_format: str | None, value: float) -> str:
    fmt = number_format or ""
    if "%" in fmt:
        return "percent"
    if "$" in fmt:
        return "USD"
    if float(value).is_integer() and "." not in fmt:
        return "count"
    return "number"


def parse_value(raw: Any, number_format: str | None = None) -> ParsedValue:
    """Normalise one cell value. Never raises; unreadable values stay as text."""
    if raw is None:
        return ParsedValue(None, "")
    if isinstance(raw, bool):
        return ParsedValue(None, str(raw))
    if isinstance(raw, (int, float)):
        return ParsedValue(float(raw), str(raw), unit=unit_from_number_format(number_format, raw))

    text = str(raw).strip()
    if not text:
        return ParsedValue(None, "")
    if NA_RE.match(text):
        return ParsedValue(None, text, qualifier="n/a")

    m = RATING_RE.match(text)
    if m:
        return ParsedValue(float(m.group(1)), text, unit="rating", scale=float(m.group(2)))

    qualifier = None
    body = text
    m = QUALIFIER_RE.match(body)
    if m:
        qualifier = QUALIFIERS.get(m.group(1).lower(), "about")
        body = m.group(2).strip()

    period = None
    m = RATE_RE.match(body)
    if m and (CURRENCY_RE.match(m.group(1).strip()) or PERCENT_RE.match(m.group(1).strip())
              or NUMBER_RE.match(m.group(1).strip())):
        period = f"per {m.group(2).lower()}"
        body = m.group(1).strip()

    def to_float(num: str) -> float:
        return float(num.replace(",", ""))

    m = CURRENCY_RE.match(body)
    if m:
        negative = bool(m.group(2)) or bool(m.group(1) and m.group(4))
        value = to_float(m.group(3))
        return ParsedValue(-value if negative else value, text, unit="USD", qualifier=qualifier, period=period)

    m = PERCENT_RE.match(body)
    if m:
        negative = bool(m.group(2)) or bool(m.group(1) and m.group(4))
        value = to_float(m.group(3)) / 100.0
        return ParsedValue(-value if negative else value, text, unit="percent", qualifier=qualifier, period=period)

    m = NUMBER_RE.match(body)
    if m:
        negative = bool(m.group(2)) or bool(m.group(1) and m.group(4))
        value = to_float(m.group(3))
        unit = "count" if value.is_integer() and "." not in m.group(3) else "number"
        return ParsedValue(-value if negative else value, text, unit=unit, qualifier=qualifier, period=period)

    return ParsedValue(None, text, qualifier=qualifier)


def format_value(value: float | None, unit: str | None, scale: float | None = None) -> str | None:
    """Human-readable version of a stored value, e.g. 0.403 -> '40.3%'."""
    if value is None:
        return None
    if unit == "percent":
        return f"{value * 100:.1f}%"
    if unit == "USD":
        return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"
    if unit == "rating":
        return f"{value:g} out of {scale:g}" if scale else f"{value:g}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.2f}"
