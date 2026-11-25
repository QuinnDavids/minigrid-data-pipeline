"""Settings shared by every step: file locations, what counts as missing, valid ranges."""

import logging
from pathlib import Path

# ---- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

SOURCE_FILES = {
    "customers": "customers.csv",
    "tariff_plans": "tariff_plans.csv",
    "meter_readings": "meter_readings.csv",
    "payments": "payments.csv",
}

PARQUET_FILE = "customer_daily.parquet"
CSV_FILE = "customer_daily.csv"
DUCKDB_FILE = "minigrid.duckdb"

# ---- The one definition of "missing" -----------------------------------------
# Compared after trimming spaces and lower-casing, so "N/A", " n/a " and "NULL" all match.
MISSING_TOKENS = {"", "n/a", "na", "none", "-", "null", "nan"}

# ---- Dates -------------------------------------------------------------------
# Tried in this order. Slash dates with the day first follow the Nigerian convention:
# 05/03/2026 means 5 March 2026.
DATE_FORMATS = [
    "%Y-%m-%d",  # 2026-03-05
    "%Y/%m/%d",  # 2026/03/05
    "%d/%m/%Y",  # 05/03/2026
    "%d %b %Y",  # 5 Mar 2026
    "%d %B %Y",  # 5 March 2026
]

# ---- Units: what to multiply each written unit by -----------------------------
# The empty string is "no unit written", which means the column's standard unit.
ENERGY_UNITS = {"": 1.0, "kwh": 1.0, "wh": 0.001}
POWER_UNITS = {"": 1.0, "kw": 1.0, "w": 0.001}
HOURS_UNITS = {"": 1.0, "h": 1.0, "hr": 1.0, "hrs": 1.0, "hours": 1.0}
HOUSEHOLD_UNITS = {"": 1.0, "people": 1.0, "persons": 1.0}

# ---- Valid ranges (inclusive). Values outside become missing. -------------------
ENERGY_KWH_RANGE = (0.0, float("inf"))
PEAK_LOAD_KW_RANGE = (0.0, 20.0)
OUTAGE_HOURS_RANGE = (0.0, 24.0)
HOUSEHOLD_SIZE_RANGE = (1, 30)
PAYMENT_AMOUNT_RANGE = (0.01, float("inf"))

# ---- Household bands ---------------------------------------------------------
HOUSEHOLD_BANDS = [("1-2", 1, 2), ("3-5", 3, 5), ("6+", 6, 30)]
UNKNOWN = "Unknown"

# ---- Booleans: only these spellings are trusted ---------------------------------
TRUE_TOKENS = {"y", "yes", "true", "t", "1"}
FALSE_TOKENS = {"n", "no", "false", "f", "0"}

# ---- Payment channels: lower-cased spelling -> official name ---------------------
CHANNELS = {
    "ussd": "USSD",
    "bank transfer": "Bank Transfer",
    "pos": "POS",
    "card": "Card",
}

# ---- Final table -------------------------------------------------------------
OUTPUT_COLUMNS = [
    "customer_id",
    "date",
    "community",
    "household_band",
    "plan_name",
    "energy_kwh",
    "peak_load_kw",
    "outage_hours",
    "energy_cost_ngn",
    "amount_paid_ngn",
    "payment_count",
    "payment_status",
]
PAID = "Paid"
NO_PAYMENT = "No payment"


def setup_logging(level: int = logging.INFO) -> None:
    """Send log messages to the terminal with a time stamp and the step name."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
