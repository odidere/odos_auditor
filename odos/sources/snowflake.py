"""Snowflake cost source.

Per-query cost comes from ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY``,
which attributes warehouse compute credits to individual queries. Notes:

* ACCOUNT_USAGE views lag by up to several hours; run audits on a schedule
  with a lookback of at least a day.
* Very short queries (around 100 ms or less) are not attributed by Snowflake.
* Warehouse idle time is not attributed to any query; see
  :meth:`SnowflakeCostSource.fetch_warehouse_usage` for idle cost.
* The role needs access to the SNOWFLAKE database (e.g. via the
  GOVERNANCE_VIEWER / USAGE_VIEWER database roles). Do not use ACCOUNTADMIN.
"""
from __future__ import annotations

import os
from typing import Any

from odos.agent.context import parse_query_tag
from odos.config import section
from odos.sources.base import CostRecord, WarehouseUsage

ATTRIBUTED_COSTS_SQL = """
SELECT
    a.query_id,
    a.query_parameterized_hash,
    a.query_tag,
    a.warehouse_name,
    a.start_time,
    a.credits_attributed_compute
        + COALESCE(a.credits_used_query_acceleration, 0) AS credits,
    q.query_text,
    q.warehouse_size,
    q.total_elapsed_time / 1000.0 AS duration_sec,
    q.bytes_scanned
FROM snowflake.account_usage.query_attribution_history a
JOIN snowflake.account_usage.query_history q
  ON q.query_id = a.query_id
WHERE a.start_time >= DATEADD('day', -%(lookback)s, CURRENT_TIMESTAMP())
  AND q.start_time >= DATEADD('day', -%(lookback)s - 1, CURRENT_TIMESTAMP())
{tag_filter}
ORDER BY a.start_time
"""

WAREHOUSE_USAGE_SQL = """
WITH metered AS (
    SELECT warehouse_name, SUM(credits_used_compute) AS credits_metered
    FROM snowflake.account_usage.warehouse_metering_history
    WHERE start_time >= DATEADD('day', -%(lookback)s, CURRENT_TIMESTAMP())
    GROUP BY 1
), attributed AS (
    SELECT warehouse_name,
           SUM(credits_attributed_compute) AS credits_attributed,
           COUNT(*) AS query_count
    FROM snowflake.account_usage.query_attribution_history
    WHERE start_time >= DATEADD('day', -%(lookback)s, CURRENT_TIMESTAMP())
    GROUP BY 1
), sizes AS (
    SELECT warehouse_name,
           MODE(warehouse_size) AS warehouse_size,
           AVG(total_elapsed_time) / 1000.0 AS avg_duration_sec
    FROM snowflake.account_usage.query_history
    WHERE start_time >= DATEADD('day', -%(lookback)s, CURRENT_TIMESTAMP())
      AND warehouse_size IS NOT NULL
    GROUP BY 1
)
SELECT m.warehouse_name,
       s.warehouse_size,
       m.credits_metered,
       COALESCE(a.credits_attributed, 0) AS credits_attributed,
       COALESCE(a.query_count, 0) AS query_count,
       COALESCE(s.avg_duration_sec, 0) AS avg_duration_sec
FROM metered m
LEFT JOIN attributed a ON a.warehouse_name = m.warehouse_name
LEFT JOIN sizes s ON s.warehouse_name = m.warehouse_name
ORDER BY m.credits_metered DESC
"""


def connect_from_env():
    """Snowflake connection from SNOWFLAKE_* environment variables."""
    import snowflake.connector

    params = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT"),
        "user": os.getenv("SNOWFLAKE_USER"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
        "role": os.getenv("SNOWFLAKE_ROLE"),
    }
    if os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE"):
        params["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]
    else:
        params["password"] = os.getenv("SNOWFLAKE_PASSWORD")
    return snowflake.connector.connect(**{k: v for k, v in params.items() if v})


class SnowflakeCostSource:
    name = "snowflake"

    def __init__(self, connection: Any = None, credit_price: float | None = None, tagged_only: bool = False):
        self._connection = connection
        self.credit_price = credit_price if credit_price is not None else float(
            section("costs").get("compute_credit_price", 3.0))
        self.tagged_only = tagged_only

    @property
    def connection(self):
        if self._connection is None:
            self._connection = connect_from_env()
        return self._connection

    def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            columns = [c[0].lower() for c in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def fetch_attributed_costs(self, lookback_days: int = 1) -> list[CostRecord]:
        tag_filter = "  AND a.query_tag ILIKE '%%\"odos\"%%'" if self.tagged_only else ""
        sql = ATTRIBUTED_COSTS_SQL.format(tag_filter=tag_filter)
        rows = self._rows(sql, {"lookback": int(lookback_days)})
        return [self.to_record(row) for row in rows]

    def to_record(self, row: dict[str, Any]) -> CostRecord:
        tag = parse_query_tag(row.get("query_tag"))
        record = CostRecord.from_mapping({
            "query_id": row.get("query_id"),
            "fingerprint": row.get("query_parameterized_hash"),
            "query_text": row.get("query_text"),
            "cost_usd": float(row.get("credits") or 0.0) * self.credit_price,
            "duration_sec": row.get("duration_sec"),
            "start_time": row.get("start_time"),
            "warehouse_name": row.get("warehouse_name"),
            "warehouse_size": row.get("warehouse_size"),
            "bytes_scanned": row.get("bytes_scanned"),
            "dag_id": tag.get("dag"),
            "task_id": tag.get("task"),
            "run_id": tag.get("run"),
        }, source=self.name)
        return record

    def fetch_warehouse_usage(self, lookback_days: int = 1) -> list[WarehouseUsage]:
        rows = self._rows(WAREHOUSE_USAGE_SQL, {"lookback": int(lookback_days)})
        return [
            WarehouseUsage(
                warehouse_name=row["warehouse_name"],
                warehouse_size=row.get("warehouse_size"),
                credits_metered=float(row.get("credits_metered") or 0.0),
                credits_attributed=float(row.get("credits_attributed") or 0.0),
                query_count=int(row.get("query_count") or 0),
                avg_duration_sec=float(row.get("avg_duration_sec") or 0.0),
            )
            for row in rows
        ]
