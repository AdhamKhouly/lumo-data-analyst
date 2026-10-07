import pytest

from src.database import PROJECT_ROOT, Database
from src.ingest import ingest
from src.modeling import weekly_table

DATA_DIR = PROJECT_ROOT / "data"
HAS_DATA = (DATA_DIR / "Week 1" / "results-dashboard.xlsx").exists()
requires_data = pytest.mark.skipif(not HAS_DATA, reason="data/ folder with weekly reports not present")


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    """The real data/ folder loaded once into a temporary database."""
    if not HAS_DATA:
        pytest.skip("data/ folder not present")
    database = Database(tmp_path_factory.mktemp("db") / "test.duckdb")
    summary = ingest(DATA_DIR, database)
    assert summary["failed"] == 0, summary["warnings"]
    yield database
    database.close()


@pytest.fixture(scope="session")
def table(db):
    return weekly_table(db)
