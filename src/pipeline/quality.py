"""Build the quality report: what came in, what was fixed, what was dropped, what went out.
Written as JSON (for machines) and Markdown (for people)."""

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def reconcile(sources: dict, payments: dict, join: dict, final_rows: int) -> dict[str, bool]:
    """Check the numbers add up: nothing appears or disappears without being counted."""
    checks = {}
    for name, stats in sources.items():
        accounted = (
            stats["rows_out"]
            + stats["dropped_missing_key"]
            + stats["exact_duplicates_removed"]
            + stats["conflicting_duplicates_merged"]
        )
        checks[f"{name}: rows in = rows out + dropped + duplicates"] = stats["rows_in"] == accounted
    checks["payments: counted + reversed + unknown flag = all clean payments"] = (
        payments["counted_in_totals"]
        + payments["reversed_excluded"]
        + payments["unknown_reversed_flag_excluded"]
        == payments["payments_total"]
    )
    checks["join: rows after outer join = final rows + unknown-customer rows"] = (
        join["rows_after_outer_join"] == final_rows + join["rows_dropped_unknown_customer"]
    )
    return checks


def build_report(
    sources: dict, payments: dict, join: dict, final: pd.DataFrame, validation: dict
) -> dict:
    return {
        "sources": sources,
        "payments": payments,
        "join": join,
        "final_table": {
            "rows": len(final),
            "customers": int(final["customer_id"].nunique()),
            "date_from": final["date"].min().date().isoformat(),
            "date_to": final["date"].max().date().isoformat(),
            "days_with_payment": int((final["payment_count"] > 0).sum()),
        },
        "reconciliation": reconcile(sources, payments, join, len(final)),
        "validation": validation,
    }


def write_json(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def tick(passed: bool) -> str:
    return "pass" if passed else "**FAIL**"


def to_markdown(report: dict) -> str:
    lines = ["# Data quality report", ""]
    final = report["final_table"]
    lines += [
        "## Final table: `customer_daily`",
        "",
        f"- **{final['rows']:,} rows**, one per customer per day",
        f"- {final['customers']} customers, {final['date_from']} to {final['date_to']}",
        f"- {final['days_with_payment']:,} customer-days with at least one counted payment",
        "",
        "## Rows per source",
        "",
        "| Source | Rows in | Exact duplicates | Duplicates merged | No key | Rows out |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in report["sources"].items():
        lines.append(
            f"| {name} | {stats['rows_in']:,} | {stats['exact_duplicates_removed']:,} | "
            f"{stats['conflicting_duplicates_merged']:,} | {stats['dropped_missing_key']:,} | "
            f"{stats['rows_out']:,} |"
        )

    lines += [
        "",
        "## Values set to missing, by rule",
        "",
        "| Source | Rule | Values |",
        "|---|---|---:|",
    ]
    for name, stats in report["sources"].items():
        for rule, count in stats["set_to_missing"].items():
            lines.append(f"| {name} | {rule} | {count:,} |")

    lines += ["", '## Missing-value markers found ("", N/A, none, -, null)', ""]
    lines += ["| Source | Column | Values |", "|---|---|---:|"]
    for name, stats in report["sources"].items():
        for column, count in stats["missing_markers"].items():
            lines.append(f"| {name} | {column} | {count:,} |")

    payments = report["payments"]
    join = report["join"]
    lines += [
        "",
        "## Payments",
        "",
        f"- {payments['payments_total']:,} clean payments",
        f"- {payments['counted_in_totals']:,} counted in daily totals",
        f"- {payments['reversed_excluded']:,} reversed (excluded)",
        f"- {payments['unknown_reversed_flag_excluded']:,} with an unknown reversed flag "
        "(excluded, never guessed)",
        f"- {payments['orphan_payments']:,} orphan payments from "
        f"{len(payments['orphan_customer_ids'])} customer IDs not in customers.csv",
        "",
        "## Joins",
        "",
        f"- {join['rows_after_outer_join']:,} customer-days after the outer join of readings "
        "and daily payments:",
        f"  - {join['rows_reading_and_payment']:,} had a reading and a payment",
        f"  - {join['rows_reading_only']:,} had a reading only",
        f"  - {join['rows_payment_only']:,} had a payment only (kept thanks to the outer join)",
        f"- {join['rows_dropped_unknown_customer']:,} dropped by the inner join (unknown customer)",
        f"- {join['rows_with_missing_plan']:,} kept with no plan (left join)",
        "",
        "## Reconciliation",
        "",
    ]
    lines += [f"- {tick(ok)}: {check}" for check, ok in report["reconciliation"].items()]
    lines += ["", "## Validation of the final table", ""]
    lines += [f"- {tick(ok)}: {check}" for check, ok in report["validation"].items()]
    return "\n".join(lines) + "\n"


def write_markdown(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(report), encoding="utf-8")
