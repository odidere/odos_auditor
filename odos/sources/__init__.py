"""Cost sources: where per-query costs come from."""
from __future__ import annotations

from odos.config import section
from odos.sources.base import CostRecord, CostSource, WarehouseUsage, normalize_records

__all__ = ["CostRecord", "CostSource", "WarehouseUsage", "normalize_records", "build_source"]


def build_source(kind: str | None = None):
    """Create the configured source: 'snowflake', 'bigquery' or 'mock'."""
    import os

    kind = (kind or os.getenv("ODOS_COST_SOURCE") or section("source").get("type", "mock")).lower()
    if kind == "snowflake":
        from odos.sources.snowflake import SnowflakeCostSource

        return SnowflakeCostSource()
    if kind == "bigquery":
        from odos.sources.bigquery import BigQueryCostSource

        return BigQueryCostSource()
    if kind == "mock":
        from odos.sources.mock import MockCostSource

        return MockCostSource()
    raise ValueError(f"Unknown cost source {kind!r}; use snowflake, bigquery or mock")
