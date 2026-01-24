import os
import random
import time
from datetime import datetime, timedelta

import psycopg2
import yaml

# Load Config manually for the script
with open("config.yaml", "r") as f:
    CONF = yaml.safe_load(f)

DB_PARAMS = CONF['database']


def get_conn():
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    return conn


def setup_schema():
    print("🐘 Connecting to Postgres & Rebuilding Schema...")
    conn = get_conn()
    cur = conn.cursor()

    # 1. Clean Slate
    cur.execute("DROP TABLE IF EXISTS pipeline_runs CASCADE;")
    cur.execute("DROP TABLE IF EXISTS data_quality_checks CASCADE;")
    cur.execute("DROP TABLE IF EXISTS lineage_nodes CASCADE;")
    cur.execute("DROP TABLE IF EXISTS lineage_edges CASCADE;")
    cur.execute("DROP TABLE IF EXISTS incidents CASCADE;")

    # 2. Pipeline Runs (OTel Traces & Metrics)
    # Measures: Latency, Throughput, Resource Util, Status
    cur.execute("""
        CREATE TABLE pipeline_runs (
            run_id SERIAL PRIMARY KEY,
            pipeline_name VARCHAR(255),
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_sec INT,
            status VARCHAR(50), -- SUCCESS, FAILED, RUNNING
            rows_processed INT,
            data_volume_mb DECIMAL(10,2),
            throughput_rows_per_sec DECIMAL(10,2),
            cost_usd DECIMAL(10,4),
            cpu_utilization_pct INT,
            memory_utilization_pct INT
        );
    """)

    # 3. Data Quality (Freshness, Accuracy)
    cur.execute("""
        CREATE TABLE data_quality_checks (
            check_id SERIAL PRIMARY KEY,
            run_id INT,
            dataset_name VARCHAR(255),
            check_type VARCHAR(50), -- NULL_CHECK, UNIQUE_CHECK, FRESHNESS
            passed BOOLEAN,
            rows_failed INT
        );
    """)

    # 4. Data Lineage (Nodes & Edges)
    cur.execute("""
        CREATE TABLE lineage_nodes (
            node_id VARCHAR(100) PRIMARY KEY,
            node_type VARCHAR(50), -- TABLE, JOB, DASHBOARD
            layer VARCHAR(50)      -- RAW, SILVER, GOLD
        );
    """)

    cur.execute("""
        CREATE TABLE lineage_edges (
            source_node VARCHAR(100),
            target_node VARCHAR(100)
        );
    """)

    # 5. Incidents (Ops Resolution)
    cur.execute("""
        CREATE TABLE incidents (
            id SERIAL PRIMARY KEY,
            pipeline_name VARCHAR(255),
            severity VARCHAR(20),
            detected_at TIMESTAMP,
            resolved_at TIMESTAMP,
            resolution_time_min INT,
            status VARCHAR(50)
        );
    """)

    print("✅ Schema Created.")
    conn.close()


def seed_data():
    conn = get_conn()
    cur = conn.cursor()

    print("🌱 Seeding Observability Data...")

    # --- 1. SEED LINEAGE ---
    nodes = [
        ('raw_salesforce', 'TABLE', 'RAW'), ('raw_web_events', 'TABLE', 'RAW'),
        ('ingest_job_sf', 'JOB', 'ETL'), ('ingest_job_web', 'JOB', 'ETL'),
        ('stg_customers', 'TABLE', 'SILVER'), ('stg_clicks', 'TABLE', 'SILVER'),
        ('dbt_transform_revenue', 'JOB', 'TRANSFORM'),
        ('fact_revenue', 'TABLE', 'GOLD'),
        ('tableau_revenue_dash', 'DASHBOARD', 'BI')
    ]
    cur.executemany("INSERT INTO lineage_nodes VALUES (%s, %s, %s)", nodes)

    edges = [
        ('raw_salesforce', 'ingest_job_sf'), ('ingest_job_sf', 'stg_customers'),
        ('raw_web_events', 'ingest_job_web'), ('ingest_job_web', 'stg_clicks'),
        ('stg_customers', 'dbt_transform_revenue'), ('stg_clicks',
                                                     'dbt_transform_revenue'),
        ('dbt_transform_revenue', 'fact_revenue'),
        ('fact_revenue', 'tableau_revenue_dash')
    ]
    cur.executemany("INSERT INTO lineage_edges VALUES (%s, %s)", edges)

    # --- 2. SEED PIPELINE METRICS (Last 30 Days) ---
    pipelines = ['ingest_job_sf', 'ingest_job_web', 'dbt_transform_revenue']

    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    current = start_date

    while current <= end_date:
        for p in pipelines:
            # Simulate Success/Fail Rate
            status = 'SUCCESS' if random.random() > 0.1 else 'FAILED'

            # Simulate Metrics
            rows = random.randint(10000, 5000000)
            duration = random.randint(30, 1200)  # seconds
            throughput = rows / duration if duration > 0 else 0
            volume_mb = rows * 0.0005
            cpu = random.randint(20, 95)

            # Timestamp logic
            run_start = current + timedelta(hours=random.randint(0, 23))
            run_end = run_start + timedelta(seconds=duration)

            cur.execute("""
                INSERT INTO pipeline_runs 
                (pipeline_name, start_time, end_time, duration_sec, status, rows_processed, 
                 data_volume_mb, throughput_rows_per_sec, cost_usd, cpu_utilization_pct, memory_utilization_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING run_id
            """, (p, run_start, run_end, duration, status, rows, volume_mb, throughput, duration * 0.05, cpu, random.randint(40, 80)))

            run_id = cur.fetchone()[0]

            # --- 3. SEED DATA QUALITY ---
            if status == 'SUCCESS':
                # Sometimes data passes pipeline but fails quality check (Data Accuracy)
                dq_passed = random.random() > 0.05
                rows_failed = 0 if dq_passed else random.randint(100, 5000)
                cur.execute("""
                    INSERT INTO data_quality_checks (run_id, dataset_name, check_type, passed, rows_failed)
                    VALUES (%s, %s, 'NULL_CHECK', %s, %s)
                """, (run_id, p + "_out", dq_passed, rows_failed))

        current += timedelta(days=1)

    print("✅ Seeded 30 days of metrics, traces, and lineage.")
    conn.close()


if __name__ == "__main__":
    setup_schema()
    seed_data()
