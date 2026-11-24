"""Snowflake storage advice: unused tables, archival candidates, clustering gaps.

Read-only: it queries ACCOUNT_USAGE and returns findings. The lifecycle policy
it generates is a template for an engineer to review, and the destructive step
is commented out.
"""
from __future__ import annotations

import re
from typing import Any

from odos.config import section

_IDENTIFIER = re.compile(r'^[A-Za-z_][\w$]*(\.[A-Za-z_][\w$]*){0,2}$')


class StorageAdvisor:
    def __init__(self, conn: Any = None) -> None:
        self._conn = conn  # connects lazily, from SNOWFLAKE_* env vars
        self.rules = section("rules")
        self.costs = section("costs")

    @property
    def conn(self):
        if self._conn is None:
            from odos.sources.snowflake import connect_from_env

            self._conn = connect_from_env()
        return self._conn

    def _execute_query(self, query: str, params: dict[str, Any]):
        import pandas as pd

        cur = self.conn.cursor()
        try:
            cur.execute(query, params)
            columns = [col[0].lower() for col in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)
        finally:
            cur.close()

    def find_ghost_tables(self):
        """Tables not read in N days and larger than the configured size."""
        cfg = self.rules["ghost_tables"]
        query = """
        WITH recent_access AS (
            SELECT DISTINCT f.value:"objectId"::INT AS id
            FROM snowflake.account_usage.access_history,
                 LATERAL FLATTEN(input => base_objects_accessed) f
            WHERE query_start_time > DATEADD('day', -%(days)s, CURRENT_TIMESTAMP())
        )
        SELECT t.table_catalog || '.' || t.table_schema || '.' || t.table_name AS table_name,
               m.active_bytes / POWER(1024, 3) AS size_gb,
               m.active_bytes / POWER(1024, 4) * %(price)s AS cost_mo,
               TO_CHAR(t.last_altered, 'YYYY-MM-DD') AS last_modified
        FROM snowflake.account_usage.tables t
        JOIN snowflake.account_usage.table_storage_metrics m ON t.table_id = m.id
        LEFT JOIN recent_access a ON t.table_id = a.id
        WHERE t.deleted IS NULL
          AND m.active_bytes > %(min_bytes)s
          AND a.id IS NULL
        ORDER BY m.active_bytes DESC
        LIMIT 20
        """
        return self._execute_query(query, {
            "days": int(cfg["days_since_last_access"]),
            "min_bytes": int(cfg["min_size_bytes"]),
            "price": float(self.costs["storage_price_per_tb_mo"]),
        })

    def find_cold_data_candidates(self):
        """Large tables whose names match the archival pattern (e.g. logs, events)."""
        cfg = self.rules["cold_data"]
        query = """
        SELECT t.table_catalog || '.' || t.table_schema || '.' || t.table_name AS table_name,
               m.active_bytes / POWER(1024, 4) AS total_size_tb,
               m.active_bytes / POWER(1024, 4) * %(price)s AS storage_cost_mo,
               'Check for old partitions to archive' AS recommendation
        FROM snowflake.account_usage.tables t
        JOIN snowflake.account_usage.table_storage_metrics m ON t.table_id = m.id
        WHERE t.deleted IS NULL
          AND m.active_bytes > %(min_bytes)s
          AND RLIKE(t.table_name, %(pattern)s, 'i')
        ORDER BY m.active_bytes DESC
        LIMIT 10
        """
        return self._execute_query(query, {
            "min_bytes": int(cfg["min_size_bytes"]),
            "pattern": str(cfg["target_tables_regex"]),
            "price": float(self.costs["storage_price_per_tb_mo"]),
        })

    def find_clustering_opportunities(self):
        """Tables whose queries scan most partitions (poor pruning), from access history."""
        cfg = self.rules["clustering"]
        query = """
        WITH scans AS (
            SELECT f.value:"objectId"::INT AS table_id,
                   COUNT(*) AS query_count,
                   AVG(q.partitions_scanned / NULLIF(q.partitions_total, 0)) AS avg_scan_ratio
            FROM snowflake.account_usage.access_history ah,
                 LATERAL FLATTEN(input => ah.base_objects_accessed) f
            JOIN snowflake.account_usage.query_history q ON q.query_id = ah.query_id
            WHERE ah.query_start_time > DATEADD('day', -7, CURRENT_TIMESTAMP())
              AND q.partitions_total > %(min_partitions)s
            GROUP BY 1
        )
        SELECT t.table_catalog || '.' || t.table_schema || '.' || t.table_name AS table_name,
               m.active_bytes / POWER(1024, 3) AS size_gb,
               s.query_count,
               s.avg_scan_ratio,
               COALESCE(t.clustering_key, 'None') AS current_cluster_key
        FROM scans s
        JOIN snowflake.account_usage.tables t ON t.table_id = s.table_id
        JOIN snowflake.account_usage.table_storage_metrics m ON t.table_id = m.id
        WHERE s.avg_scan_ratio > %(min_ratio)s
          AND m.active_bytes > %(min_bytes)s
          AND t.deleted IS NULL
        ORDER BY size_gb DESC
        LIMIT 10
        """
        return self._execute_query(query, {
            "min_partitions": int(cfg["min_partitions"]),
            "min_ratio": float(cfg["min_scan_ratio"]),
            "min_bytes": int(cfg["min_size_bytes"]),
        })

    def generate_storage_policy(self, table_name: str, date_column: str = "event_timestamp",
                                stage: str = "cold_storage_stage") -> str:
        """Archival template for review. The DELETE is commented out on purpose."""
        for name in (table_name, date_column, stage):
            if not _IDENTIFIER.match(name):
                raise ValueError(f"Not a valid identifier: {name!r}")
        months = int(int(self.rules["cold_data"]["min_data_age_days"]) / 30)
        return f"""-- Odos archival template for {table_name} (review before running)
-- Archives rows older than {months} months to an external stage.

-- 1. Export old rows (requires an existing stage, e.g. on S3 or GCS)
COPY INTO @{stage}/{table_name.replace('.', '/')}/
FROM (SELECT * FROM {table_name}
      WHERE {date_column} < DATEADD('month', -{months}, CURRENT_DATE()))
FILE_FORMAT = (TYPE = PARQUET);

-- 2. Verify the export (row counts and a sample) before deleting anything.

-- 3. Only then, remove the archived rows:
-- DELETE FROM {table_name}
-- WHERE {date_column} < DATEADD('month', -{months}, CURRENT_DATE());
"""
