"""Tests for table cleaning, de-duplication, joins and validation, using tiny hand-made tables."""

import pandas as pd
import pytest

from pipeline import transform, validate


def raw_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype=str)


CUSTOMER = {
    "customer_id": "MG-0001",
    "full_name": "Ngozi Eze",
    "phone": "08031234567",
    "email": "ngozi@example.com",
    "community": "Rumuola",
    "household_size": "4",
    "plan_id": "P01",
    "signup_date": "2026-01-05",
}


# ---- customers ---------------------------------------------------------------
class TestCleanCustomers:
    def test_duplicate_with_missing_email_keeps_the_email(self):
        copy = {**CUSTOMER, "customer_id": " mg-0001 ", "email": ""}
        table, stats = transform.clean_customers(raw_table([copy, CUSTOMER]))
        assert len(table) == 1
        assert table.loc[0, "email"] == "ngozi@example.com"
        assert stats["conflicting_duplicates_merged"] == 1

    def test_missing_community_becomes_unknown(self):
        table, _ = transform.clean_customers(raw_table([{**CUSTOMER, "community": "N/A"}]))
        assert table.loc[0, "community"] == "Unknown"

    @pytest.mark.parametrize(
        ("raw_size", "band"),
        [
            ("4", "3-5"),
            ("4 people", "3-5"),
            ("-1", "Unknown"),
            ("45", "Unknown"),
            ("1", "1-2"),
            ("7", "6+"),
            ("none", "Unknown"),
        ],
    )
    def test_household_band(self, raw_size, band):
        table, _ = transform.clean_customers(raw_table([{**CUSTOMER, "household_size": raw_size}]))
        assert table.loc[0, "household_band"] == band

    def test_out_of_range_household_is_counted(self):
        _, stats = transform.clean_customers(raw_table([{**CUSTOMER, "household_size": "45"}]))
        assert stats["set_to_missing"]["household_size: outside 1-30"] == 1

    def test_mixed_signup_dates(self):
        rows = [
            {**CUSTOMER, "customer_id": "MG-0001", "signup_date": "2026-01-05"},
            {**CUSTOMER, "customer_id": "MG-0002", "signup_date": "05/01/2026"},
            {**CUSTOMER, "customer_id": "MG-0003", "signup_date": "5 Jan 2026"},
        ]
        table, _ = transform.clean_customers(raw_table(rows))
        assert (table["signup_date"] == pd.Timestamp("2026-01-05")).all()


# ---- tariff plans ------------------------------------------------------------
def test_tariff_plans_get_one_canonical_name_and_price():
    rows = [
        {"plan_id": "P01", "plan_name": "Basic", "price_per_kwh": "₦250"},
        {"plan_id": "P01", "plan_name": "Basic", "price_per_kwh": "250"},
        {"plan_id": "P01", "plan_name": "basic ", "price_per_kwh": "250.00 NGN"},
        {"plan_id": "P01", "plan_name": "BASIC", "price_per_kwh": "250"},
    ]
    table, stats = transform.clean_tariff_plans(raw_table(rows))
    assert table.to_dict("records") == [
        {"plan_id": "P01", "plan_name": "Basic", "price_per_kwh": 250.0}
    ]
    assert stats["rows_in"] == 4 and stats["rows_out"] == 1


# ---- meter readings ----------------------------------------------------------
READING = {
    "customer_id": "MG-0001",
    "reading_date": "2026-03-05",
    "energy_used": "12.5 kWh",
    "peak_load_kw": "2.1 kW",
    "outage_hours": "3h",
}


class TestCleanMeterReadings:
    def test_units_are_converted(self):
        table, _ = transform.clean_meter_readings(raw_table([READING]))
        row = table.iloc[0]
        assert (row["energy_kwh"], row["peak_load_kw"], row["outage_hours"]) == (12.5, 2.1, 3.0)

    def test_wh_becomes_kwh(self):
        table, _ = transform.clean_meter_readings(raw_table([{**READING, "energy_used": "800 Wh"}]))
        assert table.loc[0, "energy_kwh"] == pytest.approx(0.8)

    @pytest.mark.parametrize(
        ("column", "value", "result_column"),
        [
            ("energy_used", "error", "energy_kwh"),
            ("energy_used", "-3 kWh", "energy_kwh"),
            ("peak_load_kw", "99", "peak_load_kw"),
            ("peak_load_kw", "-", "peak_load_kw"),
            ("outage_hours", "30", "outage_hours"),
        ],
    )
    def test_bad_values_become_missing_but_row_stays(self, column, value, result_column):
        table, _ = transform.clean_meter_readings(raw_table([{**READING, column: value}]))
        assert len(table) == 1
        assert pd.isna(table.loc[0, result_column])

    def test_exact_duplicates_removed(self):
        table, stats = transform.clean_meter_readings(raw_table([READING, READING]))
        assert len(table) == 1
        assert stats["exact_duplicates_removed"] == 1

    def test_conflicting_duplicate_keeps_first_non_missing_values(self):
        blank = {
            "customer_id": " mg-0001",
            "reading_date": "05/03/2026",
            "energy_used": "",
            "peak_load_kw": "null",
            "outage_hours": "-",
        }
        table, stats = transform.clean_meter_readings(raw_table([blank, READING]))
        assert len(table) == 1
        assert table.loc[0, "energy_kwh"] == 12.5
        assert stats["conflicting_duplicates_merged"] == 1

    def test_row_without_date_is_dropped_and_counted(self):
        table, stats = transform.clean_meter_readings(
            raw_table([{**READING, "reading_date": "not a date"}])
        )
        assert len(table) == 0
        assert stats["dropped_missing_key"] == 1
        assert stats["set_to_missing"]["reading_date: unparseable"] == 1


# ---- payments ----------------------------------------------------------------
def payment(payment_id, amount="₦5,000", reversed_flag="N", customer="MG-0001", day="2026-03-05"):
    return {
        "payment_id": payment_id,
        "customer_id": customer,
        "payment_date": day,
        "amount": amount,
        "channel": "ussd",
        "is_reversed": reversed_flag,
    }


class TestPayments:
    def test_same_day_payments_are_summed(self):
        raw = raw_table([payment("PAY-1", "₦5,000"), payment("PAY-2", "NGN 2000")])
        payments, _ = transform.clean_payments(raw)
        daily = transform.daily_payments(payments)
        assert daily.to_dict("records")[0]["amount_paid_ngn"] == 7000.0
        assert daily.to_dict("records")[0]["payment_count"] == 2

    def test_reversed_and_unknown_flags_are_not_counted(self):
        raw = raw_table(
            [
                payment("PAY-1", reversed_flag="N"),
                payment("PAY-2", reversed_flag="yes"),
                payment("PAY-3", reversed_flag="maybe"),
                payment("PAY-4", reversed_flag=""),
            ]
        )
        payments, _ = transform.clean_payments(raw)
        daily = transform.daily_payments(payments)
        assert daily.loc[0, "payment_count"] == 1
        customers = pd.DataFrame({"customer_id": ["MG-0001"]})
        summary = transform.summarise_payments(payments, customers)
        assert (
            summary["counted_in_totals"],
            summary["reversed_excluded"],
            summary["unknown_reversed_flag_excluded"],
        ) == (1, 1, 2)

    def test_orphan_payments_are_counted(self):
        payments, _ = transform.clean_payments(raw_table([payment("PAY-1", customer="MG-0999")]))
        summary = transform.summarise_payments(payments, pd.DataFrame({"customer_id": ["MG-0001"]}))
        assert summary["orphan_payments"] == 1


# ---- joins -------------------------------------------------------------------
def build_small_daily():
    customers, _ = transform.clean_customers(
        raw_table(
            [
                CUSTOMER,
                {**CUSTOMER, "customer_id": "MG-0002", "plan_id": "N/A"},
            ]
        )
    )
    tariffs, _ = transform.clean_tariff_plans(
        raw_table([{"plan_id": "P01", "plan_name": "Basic", "price_per_kwh": "250"}])
    )
    readings, _ = transform.clean_meter_readings(
        raw_table(
            [
                READING,  # MG-0001 on 5 March
                {**READING, "customer_id": "MG-0002"},
            ]
        )
    )
    payments, _ = transform.clean_payments(
        raw_table(
            [
                payment("PAY-1", day="2026-03-06"),  # MG-0001 pays the next day
                payment("PAY-2", customer="MG-0999", day="2026-03-05"),  # orphan
            ]
        )
    )
    return transform.build_customer_daily(
        readings, transform.daily_payments(payments), customers, tariffs
    )


class TestBuildCustomerDaily:
    def test_payment_day_without_reading_is_kept(self):
        table, stats = build_small_daily()
        row = table[(table["customer_id"] == "MG-0001") & (table["date"] == "2026-03-06")]
        assert len(row) == 1
        assert pd.isna(row.iloc[0]["energy_kwh"])
        assert row.iloc[0]["payment_status"] == "Paid"
        assert stats["rows_payment_only"] == 2

    def test_orphan_rows_are_dropped_and_counted(self):
        table, stats = build_small_daily()
        assert "MG-0999" not in set(table["customer_id"])
        assert stats["rows_dropped_unknown_customer"] == 1

    def test_customer_without_plan_is_kept(self):
        table, stats = build_small_daily()
        row = table[table["customer_id"] == "MG-0002"].iloc[0]
        assert pd.isna(row["plan_name"]) and pd.isna(row["energy_cost_ngn"])
        assert stats["rows_with_missing_plan"] == 1

    def test_energy_cost_and_defaults(self):
        table, _ = build_small_daily()
        row = table[(table["customer_id"] == "MG-0001") & (table["date"] == "2026-03-05")].iloc[0]
        assert row["energy_cost_ngn"] == 12.5 * 250
        assert row["amount_paid_ngn"] == 0.0
        assert row["payment_count"] == 0
        assert row["payment_status"] == "No payment"

    def test_result_passes_validation(self):
        table, _ = build_small_daily()
        validate.validate_customer_daily(table)


# ---- validation --------------------------------------------------------------
def test_validation_fails_loudly_on_duplicate_keys():
    table, _ = build_small_daily()
    broken = pd.concat([table, table.head(1)], ignore_index=True)
    with pytest.raises(validate.ValidationError, match="unique"):
        validate.validate_customer_daily(broken)


def test_validation_fails_on_out_of_range_outage():
    table, _ = build_small_daily()
    table.loc[0, "outage_hours"] = 30.0
    with pytest.raises(validate.ValidationError, match="outage_hours"):
        validate.validate_customer_daily(table)
