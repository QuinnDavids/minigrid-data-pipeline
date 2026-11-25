# Data quality report

## Final table: `customer_daily`

- **31,402 rows**, one per customer per day
- 300 customers, 2026-03-01 to 2026-06-28
- 4,892 customer-days with at least one counted payment

## Rows per source

| Source | Rows in | Exact duplicates | Duplicates merged | No key | Rows out |
|---|---:|---:|---:|---:|---:|
| customers | 315 | 1 | 14 | 0 | 300 |
| tariff_plans | 16 | 12 | 0 | 0 | 4 |
| meter_readings | 32,200 | 920 | 613 | 0 | 30,667 |
| payments | 5,521 | 0 | 0 | 0 | 5,521 |

## Values set to missing, by rule

| Source | Rule | Values |
|---|---|---:|
| customers | household_size: unreadable | 0 |
| customers | household_size: outside 1-30 | 11 |
| customers | signup_date: unparseable | 0 |
| tariff_plans | price_per_kwh: unreadable | 0 |
| meter_readings | reading_date: unparseable | 0 |
| meter_readings | energy_used: unreadable or unknown unit | 351 |
| meter_readings | energy_used: negative | 282 |
| meter_readings | peak_load_kw: unreadable or unknown unit | 0 |
| meter_readings | peak_load_kw: outside 0-20 | 279 |
| meter_readings | outage_hours: unreadable or unknown unit | 0 |
| meter_readings | outage_hours: outside 0-24 | 327 |
| payments | payment_date: unparseable | 0 |
| payments | amount: unreadable | 0 |
| payments | amount: zero or negative | 0 |
| payments | channel: unknown spelling | 0 |
| payments | is_reversed: unknown spelling | 61 |

## Missing-value markers found ("", N/A, none, -, null)

| Source | Column | Values |
|---|---|---:|
| customers | phone | 10 |
| customers | email | 24 |
| customers | community | 7 |
| customers | household_size | 16 |
| customers | plan_id | 5 |
| customers | signup_date | 8 |
| meter_readings | energy_used | 893 |
| meter_readings | peak_load_kw | 1,242 |
| meter_readings | outage_hours | 613 |
| payments | is_reversed | 61 |

## Payments

- 5,521 clean payments
- 5,245 counted in daily totals
- 154 reversed (excluded)
- 122 with an unknown reversed flag (excluded, never guessed)
- 108 orphan payments from 20 customer IDs not in customers.csv

## Joins

- 31,504 customer-days after the outer join of readings and daily payments:
  - 4,157 had a reading and a payment
  - 26,510 had a reading only
  - 837 had a payment only (kept thanks to the outer join)
- 102 dropped by the inner join (unknown customer)
- 425 kept with no plan (left join)

## Reconciliation

- pass: customers: rows in = rows out + dropped + duplicates
- pass: tariff_plans: rows in = rows out + dropped + duplicates
- pass: meter_readings: rows in = rows out + dropped + duplicates
- pass: payments: rows in = rows out + dropped + duplicates
- pass: payments: counted + reversed + unknown flag = all clean payments
- pass: join: rows after outer join = final rows + unknown-customer rows

## Validation of the final table

- pass: has exactly the expected columns
- pass: customer_id never missing
- pass: date never missing
- pass: (customer_id, date) is unique
- pass: community never missing
- pass: household_band uses known labels
- pass: energy_kwh is 0 or more
- pass: peak_load_kw within 0-20
- pass: outage_hours within 0-24
- pass: amount_paid_ngn never missing and 0 or more
- pass: payment_count is 0 or more
- pass: payment_status matches payment_count
- pass: energy_cost_ngn is never negative
- pass: energy_cost_ngn missing whenever energy_kwh is missing
