import os

import pandas as pd
import snowflake.connector

from odos.backend.config_loader import CONFIG


class StorageAdvisor:
    def __init__(self) -> None:
        # 1. Establish Connection
        self.conn = snowflake.connector.connect(
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            role=os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
        )

        # Load rules for easy access
        self.rules = CONFIG['rules']
        self.costs = CONFIG['costs']

    def _execute_query(self, query: str) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(query)
            columns: list[str] = [col[0].lower() for col in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)

    def find_ghost_tables(self) -> pd.DataFrame:
        """Problem 1: Tables not accessed in X days > Y size."""
        days = self.rules['ghost_tables']['days_since_last_access']
        size_bytes = self.rules['ghost_tables']['min_size_bytes']

        query = f"""
        WITH RecentAccess AS (
            SELECT DISTINCT f.value:objectId::INT as ID
            FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
            LATERAL FLATTEN(input => BASE_OBJECTS_ACCESSED) f
            WHERE QUERY_START_TIME > DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        )
        SELECT 
            t.TABLE_NAME as table_name,
            t.TABLE_SCHEMA as schema,
            CAST(m.ACTIVE_BYTES / 1024 / 1024 / 1024 AS DECIMAL(10,6)) as size_gb,
            -- Calculate cost based on config price per TB ($23 standard)
            CAST((m.ACTIVE_BYTES / 1024 / 1024 / 1024 / 1024) * {self.costs['storage_price_per_tb_mo']} AS DECIMAL(10,6)) as cost_mo,
            TO_CHAR(t.LAST_ALTERED, 'YYYY-MM-DD') as last_modified
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES t
        JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS m ON t.TABLE_ID = m.ID
        LEFT JOIN RecentAccess a ON t.TABLE_ID = a.ID
        WHERE t.DELETED IS NULL
          AND m.ACTIVE_BYTES > {size_bytes}
          AND a.ID IS NULL
        ORDER BY m.ACTIVE_BYTES DESC
        LIMIT 20;
        """
        return self._execute_query(query)

    def find_cold_data_candidates(self) -> pd.DataFrame:
        """Problem 2: Identify tables for Archival."""
        regex = self.rules['cold_data']['target_tables_regex']
        size_bytes = self.rules['cold_data']['min_size_bytes']

        query = f"""
        SELECT 
            t.TABLE_NAME as table_name,
            CAST(m.ACTIVE_BYTES / 1024 / 1024 / 1024 / 1024 AS DECIMAL(10,8)) as total_size_tb,
            CAST((m.ACTIVE_BYTES * 0.6) / 1024 / 1024 / 1024 / 1024 AS DECIMAL(10,8)) as cold_partition_size_tb,
            CAST(((m.ACTIVE_BYTES * 0.6) / 1024 / 1024 / 1024 / 1024) * {self.costs['storage_price_per_tb_mo']} AS DECIMAL(10,6)) as potential_savings,
            'Check date column partitioning' as recommendation
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES t
        JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS m ON t.TABLE_ID = m.ID
        WHERE m.ACTIVE_BYTES > {size_bytes}
          AND t.TABLE_NAME RLIKE '{regex}'
        ORDER BY m.ACTIVE_BYTES DESC
        LIMIT 10;
        """
        return self._execute_query(query)

    def find_clustering_opportunities(self) -> pd.DataFrame:
        """Problem 3: Clustering Gaps."""
        scan_ratio = self.rules['clustering']['min_scan_ratio']
        size_bytes = self.rules['clustering']['min_size_bytes']
        partitions = self.rules['clustering']['min_partitions']

        query = f"""
        WITH ScanStats AS (
            SELECT 
                REGEXP_SUBSTR(QUERY_TEXT, 'FROM ([a-zA-Z0-9_]+)', 1, 1, 'i', 1) as table_guessed,
                COUNT(*) as query_count,
                AVG(PARTITIONS_SCANNED / NULLIF(PARTITIONS_TOTAL, 0)) as avg_scan_ratio
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME > DATEADD(day, -7, CURRENT_TIMESTAMP())
              AND PARTITIONS_TOTAL > {partitions}
            GROUP BY 1
        )
        SELECT 
            t.TABLE_NAME as table_name,
            CAST(m.ACTIVE_BYTES / 1024 / 1024 / 1024 AS DECIMAL(10,6)) as size_gb,
            TO_CHAR(s.avg_scan_ratio * 100, '990.0') || '%' as avg_scan_rate,
            COALESCE(t.CLUSTERING_KEY, 'None') as current_cluster_key,
            'Suggest Clustering by Filter Predicates' as suggested_action
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES t
        JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS m ON t.TABLE_ID = m.ID
        JOIN ScanStats s ON t.TABLE_NAME = s.table_guessed
        WHERE s.avg_scan_ratio > {scan_ratio}
          AND m.ACTIVE_BYTES > {size_bytes}
        ORDER BY size_gb DESC
        LIMIT 10;
        """
        return self._execute_query(query)

    def generate_storage_policy(self, table_name: str) -> str:
        # Even the archival age is now config-driven
        months = int(self.rules['cold_data']['min_data_age_days'] / 30)
        return f"""
-- ❄️ Odos Lifecycle Policy for {table_name}
-- CONFIG: Archiving data older than {months} months ({self.rules['cold_data']['min_data_age_days']} days)

CREATE STAGE IF NOT EXISTS cold_storage_stage
  URL='s3://my-company-archive/{table_name}/'
  STORAGE_INTEGRATION = my_s3_int;

COPY INTO @cold_storage_stage/
FROM {table_name}
WHERE event_timestamp < DATEADD(month, -{months}, CURRENT_DATE())
FILE_FORMAT = (TYPE = PARQUET);

DELETE FROM {table_name}
WHERE event_timestamp < DATEADD(month, -{months}, CURRENT_DATE());
"""
