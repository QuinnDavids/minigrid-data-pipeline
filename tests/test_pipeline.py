"""End-to-end test: generate the data, run the whole pipeline, check every output."""

import importlib.util
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pipeline import config
from pipeline.__main__ import run_pipeline

GENERATOR_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_data.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_data", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Generate fresh data into a temporary folder and run the pipeline once for all tests."""
    base = tmp_path_factory.mktemp("e2e")
    load_generator().generate(base / "raw")
    report = run_pipeline(base / "raw", base / "processed", base / "reports")
    return base, report


def test_generator_is_repeatable(tmp_path):
    generator = load_generator()
    generator.generate(tmp_path / "a")
    generator.generate(tmp_path / "b")
    for name in config.SOURCE_FILES.values():
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_all_outputs_exist(run):
    base, _ = run
    for path in [
        base / "processed" / config.PARQUET_FILE,
        base / "processed" / config.CSV_FILE,
        base / "processed" / config.DUCKDB_FILE,
        base / "reports" / "quality_report.md",
        base / "reports" / "quality_report.json",
    ]:
        assert path.exists(), path


def test_final_table_has_unique_keys_and_no_missing_keys(run):
    base, _ = run
    table = pd.read_parquet(base / "processed" / config.PARQUET_FILE)
    assert list(table.columns) == config.OUTPUT_COLUMNS
    assert not table.duplicated(["customer_id", "date"]).any()
    assert table[["customer_id", "date"]].notna().all().all()


def test_csv_matches_parquet(run):
    base, _ = run
    from_csv = pd.read_csv(base / "processed" / config.CSV_FILE, encoding="utf-8-sig")
    from_parquet = pd.read_parquet(base / "processed" / config.PARQUET_FILE)
    assert list(from_csv.columns) == config.OUTPUT_COLUMNS
    assert len(from_csv) == len(from_parquet)


def test_numbers_reconcile_and_validation_passes(run):
    _, report = run
    assert all(report["reconciliation"].values())
    assert all(report["validation"].values())


def test_dates_cover_the_four_months(run):
    _, report = run
    assert report["final_table"]["date_from"] == "2026-03-01"
    assert report["final_table"]["date_to"] == "2026-06-28"


def test_the_deliberate_mess_was_found(run):
    """Each kind of dirt the generator adds should show up in the report."""
    _, report = run
    readings = report["sources"]["meter_readings"]
    assert readings["exact_duplicates_removed"] > 0
    assert readings["conflicting_duplicates_merged"] > 0
    assert readings["set_to_missing"]["energy_used: negative"] > 0
    assert readings["set_to_missing"]["energy_used: unreadable or unknown unit"] > 0
    assert readings["set_to_missing"]["peak_load_kw: outside 0-20"] > 0
    assert readings["set_to_missing"]["outage_hours: outside 0-24"] > 0
    assert report["sources"]["customers"]["rows_out"] == 300
    assert report["sources"]["tariff_plans"]["rows_out"] == 4
    assert report["payments"]["orphan_payments"] > 0
    assert report["payments"]["unknown_reversed_flag_excluded"] > 0
    assert report["join"]["rows_dropped_unknown_customer"] > 0


def test_duckdb_has_all_tables_for_project_2(run):
    base, report = run
    with duckdb.connect(str(base / "processed" / config.DUCKDB_FILE), read_only=True) as db:
        tables = {row[0] for row in db.sql("SHOW TABLES").fetchall()}
        assert tables == {
            "customer_daily",
            "customers",
            "tariff_plans",
            "meter_readings",
            "payments",
        }
        rows = db.execute("SELECT COUNT(*) FROM customer_daily").fetchone()[0]
        assert rows == report["final_table"]["rows"]
        date_type = db.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'customer_daily' AND column_name = 'date'"
        ).fetchone()[0]
        assert date_type == "DATE"
