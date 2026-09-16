"""The 17 input files of the PostgreSQL analytical layer.

Twelve processed fact CSVs and five reference CSVs. Shared by the staging DDL
generator, the loader and the independent auditor so that all three agree on
exactly which files are in scope.

Nothing here reads or imports the cleaning pipelines.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_FACT = "PROCESSED_FACT"
REFERENCE = "REFERENCE"


class InputFile(NamedTuple):
    source_path: str      # repo-relative, forward slashes
    staging_table: str    # unqualified table name in the staging schema
    file_kind: str        # PROCESSED_FACT | REFERENCE
    expected_rows: int    # data rows, excluding the header

    @property
    def path(self) -> Path:
        return PROJECT_ROOT / self.source_path


INPUT_FILES: tuple[InputFile, ...] = (
    # --- 12 processed fact CSVs -------------------------------------- 29,032
    InputFile("data/processed/cbn/fx_nfem_daily.csv",
              "stg_fx_nfem_daily", PROCESSED_FACT, 425),
    InputFile("data/processed/nbs/petrol_price_monthly.csv",
              "stg_petrol_price_monthly", PROCESSED_FACT, 2040),
    InputFile("data/processed/nbs/diesel_price_monthly.csv",
              "stg_diesel_price_monthly", PROCESSED_FACT, 2244),
    InputFile("data/processed/nbs/cooking_gas_price_monthly.csv",
              "stg_cooking_gas_price_monthly", PROCESSED_FACT, 4224),
    InputFile("data/processed/nbs/cooking_gas_extreme_callout.csv",
              "stg_cooking_gas_extreme_callout", PROCESSED_FACT, 193),
    InputFile("data/processed/nbs/transport_fare_state_monthly.csv",
              "stg_transport_fare_state_monthly", PROCESSED_FACT, 3230),
    InputFile("data/processed/nbs/transport_fare_zone_monthly.csv",
              "stg_transport_fare_zone_monthly", PROCESSED_FACT, 1785),
    InputFile("data/processed/nbs/food_price_national_monthly.csv",
              "stg_food_price_national_monthly", PROCESSED_FACT, 2142),
    InputFile("data/processed/nbs/food_price_zone_monthly.csv",
              "stg_food_price_zone_monthly", PROCESSED_FACT, 4284),
    InputFile("data/processed/nbs/food_price_extreme_callout.csv",
              "stg_food_price_extreme_callout", PROCESSED_FACT, 1428),
    InputFile("data/processed/nbs/cpi_state_monthly.csv",
              "stg_cpi_state_monthly", PROCESSED_FACT, 6512),
    InputFile("data/processed/nerc/electricity_tariff_disco_period.csv",
              "stg_electricity_tariff_disco_period", PROCESSED_FACT, 525),
    # --- 5 reference CSVs ----------------------------------------------- 176
    InputFile("data/reference/ref_state_zone.csv",
              "stg_ref_state_zone", REFERENCE, 39),
    InputFile("data/reference/ref_state_alias_observed.csv",
              "stg_ref_state_alias_observed", REFERENCE, 77),
    InputFile("data/reference/ref_transport_mode.csv",
              "stg_ref_transport_mode", REFERENCE, 6),
    InputFile("data/reference/ref_food_item.csv",
              "stg_ref_food_item", REFERENCE, 42),
    InputFile("data/reference/ref_disco.csv",
              "stg_ref_disco", REFERENCE, 12),
)

EXPECTED_FILE_COUNT = 17
EXPECTED_FACT_ROWS = 29_032
EXPECTED_REFERENCE_ROWS = 176

assert len(INPUT_FILES) == EXPECTED_FILE_COUNT
assert sum(f.expected_rows for f in INPUT_FILES
           if f.file_kind == PROCESSED_FACT) == EXPECTED_FACT_ROWS
assert sum(f.expected_rows for f in INPUT_FILES
           if f.file_kind == REFERENCE) == EXPECTED_REFERENCE_ROWS
