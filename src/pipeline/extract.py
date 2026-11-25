"""Read the raw CSV files. Every column is read as text, so nothing is converted
(or silently mangled) before the cleaning step decides what each value means."""

import logging
from pathlib import Path

import pandas as pd

from pipeline import config

logger = logging.getLogger(__name__)


def read_raw_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run 'python scripts/generate_data.py' first.")
    # keep_default_na=False: do not let pandas decide what "missing" means; config does.
    table = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    logger.info("Extracted %-20s %6d rows", path.name, len(table))
    return table


def extract_all(raw_dir: Path = config.RAW_DIR) -> dict[str, pd.DataFrame]:
    return {name: read_raw_table(raw_dir / file) for name, file in config.SOURCE_FILES.items()}
