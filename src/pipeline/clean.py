"""Reusable column-level cleaning helpers.

Every function takes a pandas Series of raw text and returns a cleaned Series with the
same index. Nothing here deletes rows: a value that cannot be trusted becomes missing.
"""

import numpy as np
import pandas as pd

from pipeline import config

# A number, optional spaces, then an optional unit made of letters: "12.5 kWh", "3h", "-1".
NUMBER_WITH_UNIT = r"^(?P<number>-?\d+(?:\.\d+)?)\s*(?P<unit>[a-z]*)$"

# An optional naira prefix, digits with optional thousands commas, an optional "ngn" suffix.
# Matches "₦5,000", "n5,000", "ngn 5000", "5000.00", "250.00 ngn" (after lower-casing).
NAIRA_AMOUNT = r"^(?:₦|ngn|n)?\s*(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?:ngn)?$"


def standardise_missing(values: pd.Series) -> pd.Series:
    """Trim spaces and turn every missing-value marker ("", "N/A", "null"...) into <NA>."""
    text = values.astype("string").str.strip()
    is_marker = text.str.lower().isin(config.MISSING_TOKENS).fillna(False) | text.isna()
    return text.mask(is_marker)


def clean_id(values: pd.Series) -> pd.Series:
    """ " mg-0042 " -> "MG-0042"."""
    return standardise_missing(values).str.upper().str.replace(r"\s+", "", regex=True)


def clean_title(values: pd.Series) -> pd.Series:
    """ "rumuola  " or "RUMUOLA" -> "Rumuola". Repeated inner spaces become one."""
    return standardise_missing(values).str.replace(r"\s+", " ", regex=True).str.title()


def parse_number_with_unit(values: pd.Series, units: dict[str, float]) -> pd.Series:
    """Pull a number out of text and convert it to a standard unit.

    `units` maps each accepted unit (lower case) to its multiplier, with "" meaning
    no unit written. "800 Wh" with {"wh": 0.001} becomes 0.8. Text that does not look
    like a number, or that uses a unit not in the map, becomes NaN.
    """
    text = standardise_missing(values).str.lower()
    parts = text.str.extract(NUMBER_WITH_UNIT)
    number = pd.to_numeric(parts["number"], errors="coerce").astype("float64")
    multiplier = parts["unit"].fillna("").map(units).astype("float64")
    return number * multiplier


def parse_naira(values: pd.Series) -> pd.Series:
    """ "₦5,000", "N5,000", "NGN 5000", "5000.00" -> 5000.0."""
    text = standardise_missing(values).str.lower()
    amount = text.str.extract(NAIRA_AMOUNT)["amount"].str.replace(",", "", regex=False)
    return pd.to_numeric(amount, errors="coerce").astype("float64")


def parse_date(values: pd.Series) -> pd.Series:
    """Parse mixed date formats in layers: each format in config.DATE_FORMATS is tried
    only on the values that are still unparsed. Anything left over becomes NaT."""
    text = standardise_missing(values)
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for date_format in config.DATE_FORMATS:
        still_unparsed = result.isna() & text.notna()
        if not still_unparsed.any():
            break
        parsed = pd.to_datetime(text[still_unparsed], format=date_format, errors="coerce")
        result.loc[still_unparsed] = parsed
    return result


def parse_bool(values: pd.Series) -> pd.Series:
    """Map known yes/no spellings to True/False. Anything else ("", "maybe") is <NA>,
    because guessing would be worse than admitting we do not know."""
    text = standardise_missing(values).str.lower()
    result = pd.Series(pd.NA, index=values.index, dtype="boolean")
    result[text.isin(config.TRUE_TOKENS).fillna(False)] = True
    result[text.isin(config.FALSE_TOKENS).fillna(False)] = False
    return result


def map_categories(values: pd.Series, mapping: dict[str, str]) -> pd.Series:
    """Map spellings to official names. Lower-cases and squeezes spaces first, so
    "bank transfer " and "BANK TRANSFER" both match "bank transfer". Unknown -> <NA>."""
    text = standardise_missing(values).str.lower().str.replace(r"\s+", " ", regex=True)
    return text.map(mapping).astype("string")


def apply_range(values: pd.Series, low: float, high: float) -> pd.Series:
    """Keep values inside [low, high]; anything outside becomes missing."""
    return values.where(values.between(low, high))


def household_band(sizes: pd.Series) -> pd.Series:
    """Group household size into "1-2", "3-5", "6+", or "Unknown"."""
    conditions = [sizes.between(low, high).fillna(False) for _, low, high in config.HOUSEHOLD_BANDS]
    labels = [label for label, _, _ in config.HOUSEHOLD_BANDS]
    bands = np.select(conditions, labels, default=config.UNKNOWN)
    return pd.Series(bands, index=sizes.index, dtype="string")


def count_newly_missing(before: pd.Series, after: pd.Series) -> int:
    """How many values were present before a step and missing after it."""
    return int((before.notna() & after.isna()).sum())
