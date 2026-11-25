"""Clean each source table, remove duplicates, then join everything into customer_daily.

Each clean_* function returns (clean_table, stats). The stats dictionary feeds the
quality report, so every row that is dropped and every value that is blanked is counted.
"""

import logging

import numpy as np
import pandas as pd

from pipeline import clean, config

logger = logging.getLogger(__name__)


# ---- Shared steps ------------------------------------------------------------
def new_stats(raw: pd.DataFrame) -> dict:
    markers = {
        column: int(clean.standardise_missing(raw[column]).isna().sum()) for column in raw.columns
    }
    return {
        "rows_in": len(raw),
        "missing_markers": {column: n for column, n in markers.items() if n},
        "set_to_missing": {},
        "dropped_missing_key": 0,
        "exact_duplicates_removed": 0,
        "conflicting_duplicates_merged": 0,
        "rows_out": 0,
    }


def record_missing(stats: dict, rule: str, before: pd.Series, after: pd.Series) -> None:
    stats["set_to_missing"][rule] = clean.count_newly_missing(before, after)


def drop_missing_keys(table: pd.DataFrame, keys: list[str], stats: dict) -> pd.DataFrame:
    """A row with no customer or no date cannot be placed anywhere, so it is dropped."""
    has_keys = table[keys].notna().all(axis=1)
    stats["dropped_missing_key"] = int((~has_keys).sum())
    return table[has_keys]


def remove_duplicates(table: pd.DataFrame, keys: list[str], stats: dict) -> pd.DataFrame:
    """Remove exact copies, then merge rows that share the same key.

    When two rows share a key but disagree (one has a value, the other is blank),
    we keep the first non-missing value in each column. groupby().first() does exactly
    that: it skips missing values column by column.
    """
    rows_before = len(table)
    table = table.drop_duplicates()
    stats["exact_duplicates_removed"] = rows_before - len(table)

    rows_before = len(table)
    table = table.groupby(keys, as_index=False, sort=False).first()
    stats["conflicting_duplicates_merged"] = rows_before - len(table)
    return table.reset_index(drop=True)


def finish(table: pd.DataFrame, stats: dict, name: str) -> tuple[pd.DataFrame, dict]:
    stats["rows_out"] = len(table)
    logger.info(
        "Cleaned  %-20s %6d in -> %6d out (%d exact dupes, %d merged, %d no key)",
        name,
        stats["rows_in"],
        stats["rows_out"],
        stats["exact_duplicates_removed"],
        stats["conflicting_duplicates_merged"],
        stats["dropped_missing_key"],
    )
    return table, stats


# ---- customers ---------------------------------------------------------------
def clean_customers(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = new_stats(raw)
    table = pd.DataFrame(index=raw.index)
    table["customer_id"] = clean.clean_id(raw["customer_id"])
    table["full_name"] = clean.clean_title(raw["full_name"])
    table["phone"] = clean.standardise_missing(raw["phone"])
    table["email"] = clean.standardise_missing(raw["email"]).str.lower()
    table["community"] = clean.clean_title(raw["community"])

    size_text = clean.standardise_missing(raw["household_size"])
    size_number = clean.parse_number_with_unit(raw["household_size"], config.HOUSEHOLD_UNITS)
    size_in_range = clean.apply_range(size_number, *config.HOUSEHOLD_SIZE_RANGE)
    record_missing(stats, "household_size: unreadable", size_text, size_number)
    record_missing(stats, "household_size: outside 1-30", size_number, size_in_range)
    table["household_size"] = size_in_range.round().astype("Int64")

    table["plan_id"] = clean.clean_id(raw["plan_id"])

    signup_text = clean.standardise_missing(raw["signup_date"])
    table["signup_date"] = clean.parse_date(raw["signup_date"])
    record_missing(stats, "signup_date: unparseable", signup_text, table["signup_date"])

    table = drop_missing_keys(table, ["customer_id"], stats)
    table = remove_duplicates(table, ["customer_id"], stats)

    # Defaults are filled only after de-duplication, so "Unknown" never beats a real value.
    table["community"] = table["community"].fillna(config.UNKNOWN)
    table["household_band"] = clean.household_band(table["household_size"])
    return finish(table, stats, "customers")


# ---- tariff_plans ------------------------------------------------------------
def clean_tariff_plans(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = new_stats(raw)
    table = pd.DataFrame(index=raw.index)
    table["plan_id"] = clean.clean_id(raw["plan_id"])
    table["plan_name"] = clean.standardise_missing(raw["plan_name"]).str.replace(
        r"\s+", " ", regex=True
    )
    price_text = clean.standardise_missing(raw["price_per_kwh"])
    table["price_per_kwh"] = clean.parse_naira(raw["price_per_kwh"])
    record_missing(stats, "price_per_kwh: unreadable", price_text, table["price_per_kwh"])

    table = drop_missing_keys(table, ["plan_id"], stats)

    # One canonical name per plan: the most common spelling, then title case.
    canonical = (
        table.dropna(subset=["plan_name"])
        .groupby("plan_id")["plan_name"]
        .agg(lambda names: names.mode().iloc[0])
        .str.title()
    )
    table["plan_name"] = table["plan_id"].map(canonical).astype("string")

    table = remove_duplicates(table, ["plan_id"], stats)
    return finish(table, stats, "tariff_plans")


# ---- meter_readings ----------------------------------------------------------
def clean_meter_readings(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = new_stats(raw)
    table = pd.DataFrame(index=raw.index)
    table["customer_id"] = clean.clean_id(raw["customer_id"])

    date_text = clean.standardise_missing(raw["reading_date"])
    table["date"] = clean.parse_date(raw["reading_date"])
    record_missing(stats, "reading_date: unparseable", date_text, table["date"])

    measures = [
        ("energy_used", "energy_kwh", config.ENERGY_UNITS, config.ENERGY_KWH_RANGE, "negative"),
        (
            "peak_load_kw",
            "peak_load_kw",
            config.POWER_UNITS,
            config.PEAK_LOAD_KW_RANGE,
            "outside 0-20",
        ),
        (
            "outage_hours",
            "outage_hours",
            config.HOURS_UNITS,
            config.OUTAGE_HOURS_RANGE,
            "outside 0-24",
        ),
    ]
    for raw_column, column, units, valid_range, range_label in measures:
        text = clean.standardise_missing(raw[raw_column])
        number = clean.parse_number_with_unit(raw[raw_column], units)
        in_range = clean.apply_range(number, *valid_range)
        record_missing(stats, f"{raw_column}: unreadable or unknown unit", text, number)
        record_missing(stats, f"{raw_column}: {range_label}", number, in_range)
        table[column] = in_range

    table = drop_missing_keys(table, ["customer_id", "date"], stats)
    table = remove_duplicates(table, ["customer_id", "date"], stats)
    return finish(table, stats, "meter_readings")


# ---- payments ----------------------------------------------------------------
def clean_payments(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = new_stats(raw)
    table = pd.DataFrame(index=raw.index)
    table["payment_id"] = clean.clean_id(raw["payment_id"])
    table["customer_id"] = clean.clean_id(raw["customer_id"])

    date_text = clean.standardise_missing(raw["payment_date"])
    table["date"] = clean.parse_date(raw["payment_date"])
    record_missing(stats, "payment_date: unparseable", date_text, table["date"])

    amount_text = clean.standardise_missing(raw["amount"])
    amount = clean.parse_naira(raw["amount"])
    table["amount_ngn"] = clean.apply_range(amount, *config.PAYMENT_AMOUNT_RANGE)
    record_missing(stats, "amount: unreadable", amount_text, amount)
    record_missing(stats, "amount: zero or negative", amount, table["amount_ngn"])

    channel_text = clean.standardise_missing(raw["channel"])
    table["channel"] = clean.map_categories(raw["channel"], config.CHANNELS)
    record_missing(stats, "channel: unknown spelling", channel_text, table["channel"])

    flag_text = clean.standardise_missing(raw["is_reversed"])
    table["is_reversed"] = clean.parse_bool(raw["is_reversed"])
    record_missing(stats, "is_reversed: unknown spelling", flag_text, table["is_reversed"])

    table = drop_missing_keys(table, ["payment_id", "customer_id", "date"], stats)
    table = remove_duplicates(table, ["payment_id"], stats)
    return finish(table, stats, "payments")


def summarise_payments(payments: pd.DataFrame, customers: pd.DataFrame) -> dict:
    """Break the cleaned payments down so every payment is accounted for."""
    known = payments["customer_id"].isin(customers["customer_id"])
    flag = payments["is_reversed"]
    return {
        "payments_total": len(payments),
        "counted_in_totals": int(flag.eq(False).fillna(False).sum()),
        "reversed_excluded": int(flag.eq(True).fillna(False).sum()),
        "unknown_reversed_flag_excluded": int(flag.isna().sum()),
        "orphan_payments": int((~known).sum()),
        "orphan_customer_ids": sorted(payments.loc[~known, "customer_id"].unique().tolist()),
    }


def daily_payments(payments: pd.DataFrame) -> pd.DataFrame:
    """One row per customer per day: total and count of payments that were NOT reversed.
    Reversed payments, and payments whose reversed flag is unknown, are left out."""
    counted = payments[payments["is_reversed"].eq(False).fillna(False)]
    return counted.groupby(["customer_id", "date"], as_index=False).agg(
        amount_paid_ngn=("amount_ngn", "sum"),
        payment_count=("payment_id", "count"),
    )


# ---- Joins -------------------------------------------------------------------
def build_customer_daily(
    readings: pd.DataFrame,
    payments_by_day: pd.DataFrame,
    customers: pd.DataFrame,
    tariffs: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    keys = ["customer_id", "date"]

    # OUTER join: a customer-day belongs in the table if there was a reading OR a payment.
    # An inner join here would lose every day someone paid but the meter did not report.
    # indicator=True adds a "_merge" column saying which side each row came from.
    combined = readings.merge(payments_by_day, on=keys, how="outer", indicator=True)
    match_counts = combined["_merge"].value_counts()

    # INNER join: only customers we actually know. Payments from customer IDs that are
    # not in customers.csv (orphans) cannot be given a community or plan, so they go.
    customer_columns = ["customer_id", "community", "household_band", "plan_id"]
    known = combined.merge(customers[customer_columns], on="customer_id", how="inner")

    # LEFT join: a customer with a missing or unknown plan still keeps their rows;
    # only plan_name and the cost come out missing.
    table = known.merge(
        tariffs[["plan_id", "plan_name", "price_per_kwh"]], on="plan_id", how="left"
    )

    table["energy_cost_ngn"] = table["energy_kwh"] * table["price_per_kwh"]
    table["amount_paid_ngn"] = table["amount_paid_ngn"].fillna(0.0)
    table["payment_count"] = table["payment_count"].fillna(0).astype("int64")
    table["payment_status"] = np.where(table["payment_count"] > 0, config.PAID, config.NO_PAYMENT)

    stats = {
        "readings_in": len(readings),
        "payment_days_in": len(payments_by_day),
        "rows_after_outer_join": len(combined),
        "rows_reading_and_payment": int(match_counts.get("both", 0)),
        "rows_reading_only": int(match_counts.get("left_only", 0)),
        "rows_payment_only": int(match_counts.get("right_only", 0)),
        "rows_dropped_unknown_customer": len(combined) - len(known),
        "rows_with_missing_plan": int(table["plan_name"].isna().sum()),
    }
    table = table[config.OUTPUT_COLUMNS].sort_values(keys).reset_index(drop=True)
    table["payment_status"] = table["payment_status"].astype("string")
    logger.info(
        "Joined   customer_daily        %6d rows (%d dropped: unknown customer)",
        len(table),
        stats["rows_dropped_unknown_customer"],
    )
    return table, stats
