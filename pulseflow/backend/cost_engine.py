import json

import snowflake.connector


class PulseFlowCostEngine:
    def __init__(self, connection_params):
        self.conn_params = connection_params

    def _get_conn(self):
        return snowflake.connector.connect(**self.conn_params)

    def fetch_attributed_costs(self, lookback_hours=24):
        CREDIT_PRICE = 3.00  # Standard Enterprise Rate

        sql = f"""
        WITH RAW_HISTORY AS (
            SELECT 
                QUERY_ID,
                START_TIME,
                END_TIME,
                TOTAL_ELAPSED_TIME,
                WAREHOUSE_NAME,
                -- Extract JSON from the comment we injected
                PARSE_JSON(REGEXP_SUBSTR(QUERY_TEXT, '\\\\{{.*\\\\}}')) as METADATA
            FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                DATEADD('hour', -{lookback_hours}, CURRENT_TIMESTAMP()),
                CURRENT_TIMESTAMP()
            ))
            WHERE QUERY_TEXT LIKE '%-- {{%' 
            AND WAREHOUSE_NAME IS NOT NULL
        ),
        
        WAREHOUSE_PRICING AS (
            SELECT * FROM (VALUES 
                ('X-SMALL', 1, 3.00), ('SMALL', 2, 6.00), ('MEDIUM', 4, 12.00),
                ('LARGE', 8, 24.00), ('X-LARGE', 16, 48.00), ('2X-LARGE', 32, 96.00)
            ) AS T(SIZE, CREDITS, HOURLY_RATE)
        ),

        CONCURRENCY_FACTOR AS (
            -- Split cost among concurrent queries
            SELECT 
                A.QUERY_ID,
                COUNT(B.QUERY_ID) as CONCURRENT_QUERIES
            FROM RAW_HISTORY A
            JOIN RAW_HISTORY B 
                ON A.WAREHOUSE_NAME = B.WAREHOUSE_NAME
                AND A.START_TIME BETWEEN B.START_TIME AND B.END_TIME
            GROUP BY A.QUERY_ID
        )

        SELECT 
            R.METADATA:dag_id::STRING as DAG_ID, -- This will be the Dagster Job Name
            R.METADATA:task_id::STRING as TASK_ID, -- This will be the Asset Name
            R.QUERY_ID,
            R.TOTAL_ELAPSED_TIME / 1000 as DURATION_SEC,
            
            -- Adjusted Cost Formula
            ((R.TOTAL_ELAPSED_TIME/1000) * (P.HOURLY_RATE/3600.0)) / C.CONCURRENCY_FACTOR as TRUE_COST_USD,
            
            CASE 
                WHEN (R.TOTAL_ELAPSED_TIME/1000) < 60 THEN 'POTENTIAL_WASTE'
                ELSE 'EFFICIENT'
            END as EFFICIENCY_TAG
            
        FROM RAW_HISTORY R
        JOIN WAREHOUSE_PRICING P ON R.WAREHOUSE_NAME LIKE '%' || P.SIZE || '%'
        JOIN CONCURRENCY_FACTOR C ON R.QUERY_ID = C.QUERY_ID
        """

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()
