import shutil

import openpyxl
import pytest

from src.database import Database
from src.ingest import discover_weeks, ingest
from tests.conftest import DATA_DIR, requires_data


def test_week_folders_sort_numerically(tmp_path):
    for name in ("Week 10", "Week 2", "Week 1", "notes"):
        (tmp_path / name).mkdir()
    assert [w for w, _ in discover_weeks(tmp_path)] == [1, 2, 10]


@requires_data
def test_all_reports_load(db):
    assert db.weeks() == list(range(1, 15))
    assert db.scalar("SELECT COUNT(*) FROM files") == 113
    assert db.company() == "Cafe A"
    assert db.scalar("SELECT COUNT(*) FROM metrics") > 1000


@requires_data
def test_second_run_skips_unchanged_files(db):
    summary = ingest(DATA_DIR, db)
    assert (summary["parsed"], summary["skipped"], summary["failed"]) == (0, 113, 0)


@requires_data
def test_changed_file_is_replaced_and_removed_file_is_purged(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR / "Week 1", data / "Week 1")
    with Database(tmp_path / "t.duckdb") as db:
        assert ingest(data, db)["parsed"] == 8
        before = db.scalar("SELECT value_numeric FROM metrics WHERE metric = 'Revenue' AND report_type = 'dashboard'")

        path = data / "Week 1" / "results-dashboard.xlsx"
        wb = openpyxl.load_workbook(path)
        wb.active["B5"] = before + 100
        wb.save(path)
        summary = ingest(data, db)
        assert (summary["parsed"], summary["skipped"]) == (1, 7)
        after = db.scalar("SELECT value_numeric FROM metrics WHERE metric = 'Revenue' AND report_type = 'dashboard'")
        assert after == pytest.approx(before + 100)
        assert db.scalar("SELECT COUNT(*) FROM metrics WHERE report_type = 'dashboard'") == 11  # no duplicates

        (data / "Week 1" / "market-survey.xlsx").unlink()
        ingest(data, db)
        assert db.scalar("SELECT COUNT(*) FROM survey_comments") == 0
        assert db.scalar("SELECT COUNT(*) FROM files") == 7
