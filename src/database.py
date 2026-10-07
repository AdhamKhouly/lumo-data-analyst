"""DuckDB storage for the parsed reports.

One row per fact, in long format: the `metrics` table holds every number from every report
with its week, report type, section, metric name, value, unit and source cell. Text lives in
`survey_comments` and `text_records`; the checkbook and daily receipts get their own tables
because their rows have a fixed shape.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path(os.environ.get("LUMO_DATA_DIR", PROJECT_ROOT / "data"))
DEFAULT_DB_PATH = Path(os.environ.get("LUMO_DB_PATH", PROJECT_ROOT / "lumo.duckdb"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_file VARCHAR PRIMARY KEY, week INTEGER, report_type VARCHAR, company VARCHAR,
    file_hash VARCHAR, ingested_at TIMESTAMP, n_metrics INTEGER, n_warnings INTEGER
);
CREATE TABLE IF NOT EXISTS metrics (
    week INTEGER, report_type VARCHAR, section VARCHAR, company VARCHAR, metric VARCHAR,
    value_numeric DOUBLE, value_text VARCHAR, unit VARCHAR, scale DOUBLE, qualifier VARCHAR,
    rank INTEGER, change_reported DOUBLE, period VARCHAR, period_label VARCHAR, line_order INTEGER,
    source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
CREATE TABLE IF NOT EXISTS survey_comments (
    week INTEGER, company VARCHAR, comment VARCHAR, weight DOUBLE, comment_order INTEGER,
    source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
CREATE TABLE IF NOT EXISTS text_records (
    week INTEGER, report_type VARCHAR, section VARCHAR, text VARCHAR, text_order INTEGER,
    source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
CREATE TABLE IF NOT EXISTS transactions (
    week INTEGER, txn_order INTEGER, date_text VARCHAR, description VARCHAR, account VARCHAR,
    payment DOUBLE, deposit DOUBLE, balance DOUBLE, source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
CREATE TABLE IF NOT EXISTS daily_receipts (
    week INTEGER, row_order INTEGER, date_text VARCHAR, day VARCHAR, daily_capacity DOUBLE,
    cups_served DOUBLE, avg_price DOUBLE, receipts DOUBLE, satisfied DOUBLE, long_wait DOUBLE,
    served_after_hours DOUBLE, left_or_outside DOUBLE, left_or_outside_text VARCHAR, is_total BOOLEAN,
    source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
CREATE TABLE IF NOT EXISTS decisions (
    week INTEGER, decision_week INTEGER, section VARCHAR, item VARCHAR, value_text VARCHAR,
    value_numeric DOUBLE, source_file VARCHAR, sheet_name VARCHAR, cell VARCHAR
);
"""

# Tables whose rows come from a single source file and are replaced when that file changes.
PER_FILE_TABLES = ["metrics", "survey_comments", "text_records", "transactions", "daily_receipts", "decisions"]


class Database:
    def __init__(self, path: str | Path | None = None, read_only: bool = False) -> None:
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.con = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            for statement in SCHEMA.strip().split(";"):
                if statement.strip():
                    self.con.execute(statement)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- writing -------------------------------------------------------------------------
    def insert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        self.con.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                             [[row.get(c) for c in columns] for row in rows])
        return len(rows)

    def delete_file(self, source_file: str) -> None:
        for table in PER_FILE_TABLES + ["files"]:
            self.con.execute(f"DELETE FROM {table} WHERE source_file = ?", [source_file])

    # -- reading -------------------------------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        cursor = self.con.execute(sql, list(params) if params else [])
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        row = self.con.execute(sql, list(params) if params else []).fetchone()
        return row[0] if row else None

    def weeks(self) -> list[int]:
        return [r["week"] for r in self.query("SELECT DISTINCT week FROM files ORDER BY week")]

    def company(self) -> str | None:
        """The cafe the reports belong to: the company named in most report titles."""
        return self.scalar("SELECT company FROM files WHERE company IS NOT NULL "
                           "GROUP BY company ORDER BY COUNT(*) DESC LIMIT 1")
