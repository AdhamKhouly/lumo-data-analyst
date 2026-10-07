"""Find the weekly report folders, parse every workbook, and load the results into DuckDB.

    python -m src.ingest            # parse new or changed files only
    python -m src.ingest --force    # re-parse everything

Week folders are named "Week 1", "Week 2", ... and are sorted numerically, so Week 10 comes
after Week 9 rather than after Week 1. Each file's SHA-256 hash is stored, which makes
re-running cheap: unchanged files are skipped and a corrected file simply replaces its
old rows.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .database import DEFAULT_DATA_DIR, DEFAULT_DB_PATH, Database
from .parsers import parse_report, report_type_for

log = logging.getLogger("lumo.ingest")
WEEK_FOLDER_RE = re.compile(r"^\s*week\s*(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ReportFile:
    week: int
    path: Path
    source_file: str   # "Week 7/results-dashboard.xlsx", used as the provenance key
    report_type: str | None


def discover_weeks(data_dir: Path) -> list[tuple[int, Path]]:
    weeks = []
    for folder in data_dir.iterdir() if data_dir.exists() else []:
        m = WEEK_FOLDER_RE.match(folder.name)
        if folder.is_dir() and m:
            weeks.append((int(m.group(1)), folder))
    return sorted(weeks)


def discover_reports(data_dir: Path) -> list[ReportFile]:
    reports = []
    for week, folder in discover_weeks(data_dir):
        for path in sorted(folder.glob("*.xlsx")):
            if path.name.startswith("~$"):
                continue  # Excel lock files
            reports.append(ReportFile(week, path, f"{folder.name}/{path.name}", report_type_for(path.name)))
    return reports


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ingest(data_dir: Path | None = None, db: Database | None = None, force: bool = False) -> dict[str, Any]:
    """Parse new or changed reports into the database. Returns a summary of what happened."""
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    own_db = db is None
    db = db or Database()
    summary: dict[str, Any] = {"weeks": [], "parsed": 0, "skipped": 0, "failed": 0, "unsupported": 0, "warnings": []}
    try:
        reports = discover_reports(data_dir)
        summary["weeks"] = sorted({r.week for r in reports})
        known = {r["source_file"]: r["file_hash"] for r in db.query("SELECT source_file, file_hash FROM files")}
        for report in reports:
            digest = file_hash(report.path)
            if not force and known.get(report.source_file) == digest:
                summary["skipped"] += 1
                continue
            if report.report_type is None:
                summary["unsupported"] += 1
                log.warning("no parser for %s; skipped", report.source_file)
                continue
            try:
                parsed = parse_report(report.path, report.week, report.source_file)
            except Exception as exc:  # noqa: BLE001 - one bad file should not stop the rest
                summary["failed"] += 1
                summary["warnings"].append(f"{report.source_file}: {type(exc).__name__}: {exc}")
                log.error("failed to parse %s: %s", report.source_file, exc)
                continue
            db.con.execute("BEGIN")
            db.delete_file(report.source_file)
            db.insert("metrics", parsed.metrics)
            db.insert("survey_comments", parsed.comments)
            db.insert("text_records", parsed.text_records)
            db.insert("transactions", parsed.transactions)
            db.insert("daily_receipts", parsed.daily_receipts)
            db.insert("decisions", parsed.decisions)
            db.insert("files", [{"source_file": report.source_file, "week": report.week,
                                 "report_type": report.report_type, "company": parsed.company,
                                 "file_hash": digest, "ingested_at": datetime.now(),
                                 "n_metrics": len(parsed.metrics), "n_warnings": len(parsed.warnings)}])
            db.con.execute("COMMIT")
            summary["parsed"] += 1
            for warning in parsed.warnings:
                summary["warnings"].append(f"{report.source_file}: {warning}")
            log.info("parsed %s (%d metrics)", report.source_file, len(parsed.metrics))

        # Files that disappeared from disk should disappear from the database too.
        present = {r.source_file for r in reports}
        for gone in [k for k in known if k not in present]:
            db.delete_file(gone)
            log.info("removed %s (no longer on disk)", gone)
    finally:
        if own_db:
            db.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load the weekly Excel reports into DuckDB.")
    ap.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="folder containing the Week N folders")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH), help="DuckDB file to create or update")
    ap.add_argument("--force", action="store_true", help="re-parse files even if they have not changed")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    with Database(args.db) as db:
        summary = ingest(Path(args.data), db, force=args.force)
        weeks = summary["weeks"]
        print(f"Weeks found: {len(weeks)}" + (f" (Week {weeks[0]} to Week {weeks[-1]})" if weeks else ""))
        print(f"Files parsed: {summary['parsed']}, unchanged: {summary['skipped']}, "
              f"failed: {summary['failed']}, unsupported: {summary['unsupported']}")
        print(f"Metrics stored: {db.scalar('SELECT COUNT(*) FROM metrics')}, "
              f"survey comments: {db.scalar('SELECT COUNT(*) FROM survey_comments')}, "
              f"transactions: {db.scalar('SELECT COUNT(*) FROM transactions')}")
        for warning in summary["warnings"]:
            print(f"  warning: {warning}")
        print(f"Database: {args.db}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
