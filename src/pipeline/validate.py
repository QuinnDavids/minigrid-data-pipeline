"""Final checks on customer_daily. If any check fails the pipeline stops loudly
instead of saving a table that looks fine but is wrong."""

import logging

import pandas as pd

from pipeline import config

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when the final table breaks one or more rules."""


def within(values: pd.Series, low: float, high: float) -> bool:
    """True when every value that is present lies in [low, high]. Missing is allowed."""
    present = values.dropna()
    return bool(present.between(low, high).all())


def check_customer_daily(table: pd.DataFrame) -> dict[str, bool]:
    """Run every rule and return {rule description: passed?}."""
    bands = {label for label, _, _ in config.HOUSEHOLD_BANDS} | {config.UNKNOWN}
    paid = table["payment_count"] > 0
    return {
        "has exactly the expected columns": list(table.columns) == config.OUTPUT_COLUMNS,
        "customer_id never missing": bool(table["customer_id"].notna().all()),
        "date never missing": bool(table["date"].notna().all()),
        "(customer_id, date) is unique": not table.duplicated(["customer_id", "date"]).any(),
        "community never missing": bool(table["community"].notna().all()),
        "household_band uses known labels": bool(table["household_band"].isin(bands).all()),
        "energy_kwh is 0 or more": within(table["energy_kwh"], *config.ENERGY_KWH_RANGE),
        "peak_load_kw within 0-20": within(table["peak_load_kw"], *config.PEAK_LOAD_KW_RANGE),
        "outage_hours within 0-24": within(table["outage_hours"], *config.OUTAGE_HOURS_RANGE),
        "amount_paid_ngn never missing and 0 or more": bool(
            table["amount_paid_ngn"].notna().all() and (table["amount_paid_ngn"] >= 0).all()
        ),
        "payment_count is 0 or more": bool((table["payment_count"] >= 0).all()),
        "payment_status matches payment_count": bool(
            (table.loc[paid, "payment_status"] == config.PAID).all()
            and (table.loc[~paid, "payment_status"] == config.NO_PAYMENT).all()
        ),
        "energy_cost_ngn is never negative": within(table["energy_cost_ngn"], 0, float("inf")),
        "energy_cost_ngn missing whenever energy_kwh is missing": bool(
            table.loc[table["energy_kwh"].isna(), "energy_cost_ngn"].isna().all()
        ),
    }


def validate_customer_daily(table: pd.DataFrame) -> dict[str, bool]:
    results = check_customer_daily(table)
    failed = [rule for rule, passed in results.items() if not passed]
    if failed:
        raise ValidationError("customer_daily failed: " + "; ".join(failed))
    logger.info("Validated customer_daily: all %d checks passed", len(results))
    return results
