"""Save the results: customer_daily as Parquet, and every clean table into DuckDB."""

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def with_plain_dates(table: pd.DataFrame) -> pd.DataFrame:
    """Store date-time columns as plain dates (no time part), so they load as DATE."""
    table = table.copy()
    for column in table.select_dtypes(include="datetime").columns:
        table[column] = table[column].dt.date
    return table


def to_parquet(table: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with_plain_dates(table).to_parquet(path, index=False)
    logger.info("Loaded   %-28s %6d rows", path.name, len(table))


def to_csv(table: pd.DataFrame, path: Path) -> None:
    """A copy anyone can open in Excel. utf-8-sig makes Excel read the text correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with_plain_dates(table).to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Loaded   %-28s %6d rows", path.name, len(table))


def to_duckdb(tables: dict[str, pd.DataFrame], path: Path) -> None:
    """Write each table into the DuckDB file, replacing any earlier version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as connection:
        for name, table in tables.items():
            connection.register("incoming", with_plain_dates(table))
            connection.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM incoming')
            connection.unregister("incoming")
            logger.info("Loaded   %s table %-16s %6d rows", path.name, name, len(table))
