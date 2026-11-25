"""Tests for the column-level cleaning helpers, one group per helper."""

import math

import pandas as pd
import pytest

from pipeline import clean, config


def as_series(*values):
    return pd.Series(list(values), dtype="string")


def is_missing(value) -> bool:
    return value is pd.NA or value is pd.NaT or (isinstance(value, float) and math.isnan(value))


# ---- standardise_missing -----------------------------------------------------
class TestStandardiseMissing:
    @pytest.mark.parametrize(
        "marker", ["", "N/A", "n/a", "none", "None", "-", "null", "NULL", "  "]
    )
    def test_markers_become_missing(self, marker):
        assert is_missing(clean.standardise_missing(as_series(marker))[0])

    def test_real_values_are_trimmed_not_removed(self):
        assert clean.standardise_missing(as_series("  Rumuola ")).tolist() == ["Rumuola"]

    def test_word_containing_a_marker_is_kept(self):
        # "Nonso" starts with "no" and contains "none"-like letters, but is a real value.
        assert clean.standardise_missing(as_series("Nonso")).tolist() == ["Nonso"]


# ---- clean_id ----------------------------------------------------------------
class TestCleanId:
    @pytest.mark.parametrize("raw", [" mg-0042 ", "MG-0042", "mg-0042", " MG-0042"])
    def test_variants_become_one_id(self, raw):
        assert clean.clean_id(as_series(raw)).tolist() == ["MG-0042"]

    def test_missing_id_stays_missing(self):
        assert is_missing(clean.clean_id(as_series("N/A"))[0])


# ---- clean_title -------------------------------------------------------------
class TestCleanTitle:
    @pytest.mark.parametrize("raw", ["Rumuola", "rumuola ", "RUMUOLA", " rumuola"])
    def test_community_spellings_match(self, raw):
        assert clean.clean_title(as_series(raw)).tolist() == ["Rumuola"]

    def test_inner_spaces_are_squeezed(self):
        assert clean.clean_title(as_series("productive   use")).tolist() == ["Productive Use"]


# ---- parse_number_with_unit --------------------------------------------------
class TestParseNumberWithUnit:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("12.5 kWh", 12.5), ("800 Wh", 0.8), ("1.2kwh", 1.2), ("3.4", 3.4), ("-2.0 kWh", -2.0)],
    )
    def test_energy_is_converted_to_kwh(self, raw, expected):
        result = clean.parse_number_with_unit(as_series(raw), config.ENERGY_UNITS)[0]
        assert result == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["error", "", "kWh", "12.5 litres"])
    def test_unreadable_or_unknown_unit_becomes_missing(self, raw):
        result = clean.parse_number_with_unit(as_series(raw), config.ENERGY_UNITS)[0]
        assert is_missing(result)

    def test_peak_load_with_unit(self):
        result = clean.parse_number_with_unit(as_series("2.1 kW", "-"), config.POWER_UNITS)
        assert result[0] == pytest.approx(2.1)
        assert is_missing(result[1])

    def test_outage_hours_with_h(self):
        result = clean.parse_number_with_unit(as_series("3h", "30"), config.HOURS_UNITS)
        assert result.tolist() == [3.0, 30.0]

    def test_household_written_as_text(self):
        result = clean.parse_number_with_unit(as_series("4 people", "4"), config.HOUSEHOLD_UNITS)
        assert result.tolist() == [4.0, 4.0]


# ---- parse_naira -------------------------------------------------------------
class TestParseNaira:
    @pytest.mark.parametrize("raw", ["₦5,000", "N5,000", "NGN 5000", "5000.00", "5000", "5000 NGN"])
    def test_all_formats_give_the_same_amount(self, raw):
        assert clean.parse_naira(as_series(raw))[0] == pytest.approx(5000.0)

    def test_tariff_price_formats(self):
        result = clean.parse_naira(as_series("₦250", "250", "250.00 NGN"))
        assert result.tolist() == [250.0, 250.0, 250.0]

    @pytest.mark.parametrize("raw", ["", "five thousand", "N/A"])
    def test_unreadable_amount_becomes_missing(self, raw):
        assert is_missing(clean.parse_naira(as_series(raw))[0])


# ---- parse_date --------------------------------------------------------------
class TestParseDate:
    @pytest.mark.parametrize("raw", ["2026-03-05", "05/03/2026", "5 Mar 2026", "2026/03/05"])
    def test_all_formats_give_5_march(self, raw):
        assert clean.parse_date(as_series(raw))[0] == pd.Timestamp("2026-03-05")

    def test_slash_dates_are_day_first(self):
        # Nigerian convention: 01/02/2026 is 1 February, not 2 January.
        assert clean.parse_date(as_series("01/02/2026"))[0] == pd.Timestamp("2026-02-01")

    @pytest.mark.parametrize("raw", ["", "yesterday", "31/02/2026", "null"])
    def test_unparseable_dates_become_missing(self, raw):
        assert is_missing(clean.parse_date(as_series(raw))[0])

    def test_mixed_column(self):
        result = clean.parse_date(as_series("2026-01-05", "05/01/2026", "5 Jan 2026"))
        assert result.nunique() == 1


# ---- parse_bool --------------------------------------------------------------
class TestParseBool:
    @pytest.mark.parametrize("raw", ["Y", "yes", "1", "TRUE", "true"])
    def test_true_spellings(self, raw):
        assert clean.parse_bool(as_series(raw))[0] == True  # noqa: E712

    @pytest.mark.parametrize("raw", ["N", "no", "0", "false", "FALSE"])
    def test_false_spellings(self, raw):
        assert clean.parse_bool(as_series(raw))[0] == False  # noqa: E712

    @pytest.mark.parametrize("raw", ["", "maybe", "unknown"])
    def test_unknown_spellings_are_missing_not_guessed(self, raw):
        assert is_missing(clean.parse_bool(as_series(raw))[0])


# ---- map_categories ----------------------------------------------------------
class TestMapCategories:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("USSD", "USSD"),
            ("ussd", "USSD"),
            (" Ussd", "USSD"),
            ("bank transfer ", "Bank Transfer"),
            ("BANK TRANSFER", "Bank Transfer"),
            ("pos", "POS"),
            ("Card", "Card"),
        ],
    )
    def test_channel_spellings(self, raw, expected):
        assert clean.map_categories(as_series(raw), config.CHANNELS).tolist() == [expected]

    def test_unknown_channel_becomes_missing(self):
        assert is_missing(clean.map_categories(as_series("cheque"), config.CHANNELS)[0])


# ---- apply_range -------------------------------------------------------------
class TestApplyRange:
    def test_values_outside_range_become_missing(self):
        values = pd.Series([-1.0, 0.0, 12.0, 24.0, 30.0])
        result = clean.apply_range(values, *config.OUTAGE_HOURS_RANGE)
        assert result.isna().tolist() == [True, False, False, False, True]

    def test_rows_are_not_deleted(self):
        values = pd.Series([99.0, 2.1])
        assert len(clean.apply_range(values, *config.PEAK_LOAD_KW_RANGE)) == 2


# ---- household_band ----------------------------------------------------------
class TestHouseholdBand:
    def test_bands(self):
        sizes = pd.Series([1, 2, 3, 5, 6, 30, None], dtype="Int64")
        assert clean.household_band(sizes).tolist() == [
            "1-2",
            "1-2",
            "3-5",
            "3-5",
            "6+",
            "6+",
            "Unknown",
        ]


# ---- count_newly_missing -----------------------------------------------------
def test_count_newly_missing():
    before = pd.Series([1.0, None, 3.0, 4.0])
    after = pd.Series([1.0, None, None, None])
    assert clean.count_newly_missing(before, after) == 2
