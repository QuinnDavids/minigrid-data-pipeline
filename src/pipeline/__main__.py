"""Command line entry point:  python -m pipeline run"""

import argparse
import logging
import sys
from pathlib import Path

from pipeline import config, extract, load, quality, transform, validate

logger = logging.getLogger("pipeline")


def run_pipeline(
    raw_dir: Path = config.RAW_DIR,
    processed_dir: Path = config.PROCESSED_DIR,
    reports_dir: Path = config.REPORTS_DIR,
) -> dict:
    """Run every step in order and return the quality report."""
    # 1. Extract: everything as text.
    raw = extract.extract_all(raw_dir)

    # 2. Clean and de-duplicate each table on its own.
    customers, customer_stats = transform.clean_customers(raw["customers"])
    tariffs, tariff_stats = transform.clean_tariff_plans(raw["tariff_plans"])
    readings, reading_stats = transform.clean_meter_readings(raw["meter_readings"])
    payments, payment_stats = transform.clean_payments(raw["payments"])

    # 3. Roll payments up to one row per customer per day, then join everything.
    payment_summary = transform.summarise_payments(payments, customers)
    payments_by_day = transform.daily_payments(payments)
    customer_daily, join_stats = transform.build_customer_daily(
        readings, payments_by_day, customers, tariffs
    )

    # 4. Validate: stop here if anything is wrong.
    validation = validate.validate_customer_daily(customer_daily)

    # 5. Load.
    load.to_parquet(customer_daily, processed_dir / config.PARQUET_FILE)
    load.to_csv(customer_daily, processed_dir / config.CSV_FILE)
    load.to_duckdb(
        {
            "customer_daily": customer_daily,
            "customers": customers,
            "tariff_plans": tariffs,
            "meter_readings": readings,
            "payments": payments,
        },
        processed_dir / config.DUCKDB_FILE,
    )

    # 6. Quality report.
    sources = {
        "customers": customer_stats,
        "tariff_plans": tariff_stats,
        "meter_readings": reading_stats,
        "payments": payment_stats,
    }
    report = quality.build_report(sources, payment_summary, join_stats, customer_daily, validation)
    quality.write_json(report, reports_dir / "quality_report.json")
    quality.write_markdown(report, reports_dir / "quality_report.md")
    logger.info("Quality report written to %s", reports_dir)

    failed = [check for check, ok in report["reconciliation"].items() if not ok]
    if failed:
        raise validate.ValidationError("Numbers do not reconcile: " + "; ".join(failed))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__)
    # Optional, so the VS Code Run button (which passes no arguments) also works.
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run"], help="'run' runs the whole pipeline"
    )
    parser.parse_args()
    config.setup_logging()
    run_pipeline()
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
