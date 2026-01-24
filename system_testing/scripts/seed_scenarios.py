from odos.backend.db import get_db_connection  # <--- NEW IMPORT
import os
import random
import sys
from datetime import datetime, timedelta

import psycopg2
import yaml

# Robust Path Setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

# Fix: Add Project Root to Path so we can import 'odos'
sys.path.append(PROJECT_ROOT)


# --- LOAD CONFIGURATION ---
def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("⚠️ Config not found, using defaults.")
        return {'anomalies': {'high_severity_threshold_usd': 15.0}, 'database': {}}
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


CONF = load_config()
DB_PARAMS = CONF.get('database', {})
ANOMALY_RULES = CONF.get('rules', {}).get('anomalies', {})
HIGH_SEVERITY_THRESHOLD = ANOMALY_RULES.get(
    'high_severity_threshold_usd', 15.0)

# --- 1. FINANCIAL SCENARIOS (Full SQL Rewrites) ---
SCENARIO_LIBRARY = {
    "mktg": [
        {"bad": "SELECT * FROM raw_leads t1, metadata t2", "fix": "SELECT t1.*, t2.campaign_name \nFROM raw_leads t1 \nJOIN metadata t2 ON t1.campaign_id = t2.id",
            "diag": "⚠️ Implicit Cartesian Join (Row Explosion)"},
        {"bad": "SELECT * FROM web_events WHERE json_extract(data, '$.id') = '123'",
         "fix": "SELECT * FROM web_events \nWHERE user_id_extracted = '123'", "diag": "⚠️ JSON Scan in WHERE (No Pruning)"},
        {"bad": "SELECT DISTINCT email FROM huge_campaign_logs",
            "fix": "SELECT HLL(email) FROM huge_campaign_logs", "diag": "⚠️ Exact Count Distinct on High Cardinality"},
        {"bad": "SELECT * FROM leads ORDER BY created_at DESC", "fix": "SELECT * FROM leads \nORDER BY created_at DESC \nLIMIT 100",
            "diag": "⚠️ Unbounded Sort on Large Table (Memory Spill)"}
    ],
    "eng": [
        {"bad": "SELECT * FROM app_logs WHERE TO_CHAR(ts, 'YYYY-MM-DD') = '2024-01-01'",
         "fix": "SELECT * FROM app_logs \nWHERE ts >= '2024-01-01 00:00:00' \nAND ts < '2024-01-02 00:00:00'", "diag": "⚠️ SARGability Violation (Function on Column)"},
        {"bad": "SELECT * FROM logs WHERE msg LIKE '%error%'",
            "fix": "SELECT * FROM logs \nWHERE CONTAINS(msg, 'error')", "diag": "⚠️ Leading Wildcard Scan (Full Table Scan)"},
        {"bad": "SELECT t1.*, t2.* FROM logs t1 JOIN users t2 ON t1.uid = t2.uid",
            "fix": "SELECT t1.ts, t1.msg, t2.username \nFROM logs t1 \nJOIN users t2 ON t1.uid = t2.uid", "diag": "⚠️ Select * on Wide Tables (Network Saturation)"},
        {"bad": "DELETE FROM audit_logs WHERE ts < NOW() - INTERVAL '1 year'", "fix": "ALTER TABLE audit_logs DROP PARTITION WHERE ts < '2025-01-01'",
         "diag": "⚠️ Mass Delete Anti-Pattern (Use Partitioning)"}
    ],
    "ds": [
        {"bad": "SELECT * FROM clickstream_10tb",
            "fix": "SELECT * FROM clickstream_10tb SAMPLE(1)", "diag": "⚠️ Select * on Petabyte Table (Client Crash Risk)"},
        {"bad": "SELECT UDF_PROCESS(img) FROM images", "fix": "SELECT BATCH_PROCESS(img) FROM images",
         "diag": "⚠️ Slow Scalar UDF (Blocks Parallelism)"},
        {"bad": "SELECT t1.id FROM training t1 CROSS JOIN validation t2",
            "fix": "SELECT t1.id \nFROM training t1 \nINNER JOIN validation t2 ON t1.model_id = t2.model_id", "diag": "⚠️ Accidental Cross Join in Feature Eng"},
        {"bad": "WITH dataset AS (SELECT * FROM raw) SELECT * FROM dataset WHERE id > 100",
         "fix": "SELECT * FROM raw WHERE id > 100", "diag": "⚠️ Late Filtering (Reading unnecessary bytes)"}
    ],
    "fin": [
        {"bad": "INSERT INTO ledger VALUES (101, 'USD', 50.00)", "fix": "COPY INTO ledger \nFROM @stage/payments/batch_01.csv \nFILE_FORMAT = (TYPE = CSV)",
         "diag": "⚠️ Single Row Inserts (Micro-partition fragmentation)"},
        {"bad": "SELECT * FROM payments WHERE amount > 1000",
            "fix": "ALTER TABLE payments CLUSTER BY (amount);\nSELECT * FROM payments WHERE amount > 1000", "diag": "⚠️ Poor Clustering (Scanning 90% of partitions)"},
        {"bad": "SELECT t1.id, SUM(t2.amt) FROM trans t1 JOIN items t2 GROUP BY 1",
         "fix": "SELECT id, total_amt FROM precomputed_daily_agg", "diag": "⚠️ Expensive Aggregation on Raw Data"},
        {"bad": "UPDATE accounts SET bal = bal + 1 WHERE id = 500",
            "fix": "MERGE INTO accounts t1 USING updates t2 \nON t1.id = t2.id \nWHEN MATCHED THEN UPDATE SET t1.bal = t2.new_bal", "diag": "⚠️ Row Lock Contention (High Latency)"}
    ]
}

# --- 2. PIPELINE SCENARIOS (Diverse Failures) ---
PIPELINE_TEMPLATES = [
    # Infrastructure Failures
    {"name": "ingest_salesforce_raw", "base_dur": 45, "fail_prob": 0.05,
        "error": "ConnectionTimeout: API Endpoint 10.0.0.5 Unreachable"},
    {"name": "k8s_pod_autoscaler", "base_dur": 10, "fail_prob": 0.15,
        "error": "ResourceExhausted: No nodes available to schedule pod"},

    # Data Quality Issues
    {"name": "dbt_transform_revenue", "base_dur": 120, "fail_prob": 0.10,
        "error": "SchemaMismatch: Column 'customer_ltv' missing in source"},
    {"name": "email_campaign_validator", "base_dur": 25, "fail_prob": 0.08,
        "error": "DataQualityError: 5000 emails contain invalid characters"},

    # Resource Limits
    {"name": "train_churn_model_v2", "base_dur": 600, "fail_prob": 0.20,
        "error": "OOMKilled: Container reached memory limit (8GB)"},
    {"name": "quarterly_report_gen", "base_dur": 300, "fail_prob": 0.12,
        "error": "DiskFull: /tmp usage exceeded 100GB"},

    # Logic & Code Errors
    {"name": "hourly_payment_recon", "base_dur": 15, "fail_prob": 0.02,
        "error": "NullPointer: Transaction ID cannot be None"},
    {"name": "currency_conversion", "base_dur": 8, "fail_prob": 0.05,
        "error": "ZeroDivisionError: Exchange rate cannot be 0"},

    # Security & Permissions
    {"name": "gdpr_deletion_job", "base_dur": 50, "fail_prob": 0.10,
        "error": "PermissionDenied: Service Account lacks DELETE on table 'users'"},
    {"name": "reverse_etl_hubspot", "base_dur": 30, "fail_prob": 0.08,
        "error": "RateLimitExceeded: Upstream API throttling active (429)"},

    # Database Specific
    {"name": "inventory_sync", "base_dur": 40, "fail_prob": 0.05,
        "error": "DeadlockDetected: Process 1234 waiting for ShareLock on transaction"},
    {"name": "legacy_migration", "base_dur": 180, "fail_prob": 0.03,
        "error": "SerializationFailure: could not serialize access due to concurrent update"}
]


def setup_schema(cur):
    print("🏗️  Rebuilding Full Database Schema...")

    cur.execute("DROP TABLE IF EXISTS audit_events CASCADE;")
    cur.execute("DROP TABLE IF EXISTS query_fingerprints CASCADE;")
    cur.execute("DROP TABLE IF EXISTS pipeline_runs CASCADE;")
    cur.execute("DROP TABLE IF EXISTS lineage_nodes CASCADE;")
    cur.execute("DROP TABLE IF EXISTS lineage_edges CASCADE;")

    # Financial Tables
    cur.execute("""
        CREATE TABLE audit_events (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP,
            task_id VARCHAR(255),
            waste_usd DECIMAL(10,2),
            severity VARCHAR(50),
            duration_seconds INT
        );
    """)

    cur.execute("""
        CREATE TABLE query_fingerprints (
            hash_id VARCHAR(255) PRIMARY KEY,
            sql_text TEXT,
            optimized_sql_text TEXT,
            diagnosis_text TEXT,
            execution_count INT,
            avg_cost_usd DECIMAL(10,2)
        );
    """)

    # Observability Tables
    cur.execute("""
        CREATE TABLE pipeline_runs (
            run_id SERIAL PRIMARY KEY,
            pipeline_name VARCHAR(255),
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_sec DECIMAL(10,2),
            status VARCHAR(50),
            rows_processed INT,
            throughput_rows_per_sec DECIMAL(10,2),
            cpu_utilization_pct INT,
            error_message TEXT,
            stack_trace TEXT,
            ai_diagnosis TEXT,
            ai_suggested_fix TEXT
        );
    """)

    # Lineage Tables
    cur.execute("""
        CREATE TABLE lineage_nodes (
            node_id VARCHAR(100) PRIMARY KEY,
            node_type VARCHAR(50),
            layer VARCHAR(50)
        );
    """)
    cur.execute("""
        CREATE TABLE lineage_edges (
            source_node VARCHAR(100),
            target_node VARCHAR(100)
        );
    """)


def seed_lineage(cur):
    print("🕸️  Seeding Data Lineage...")
    nodes = [
        ('raw_salesforce', 'TABLE', 'RAW'), ('ingest_job', 'JOB', 'ETL'),
        ('stg_customers', 'TABLE', 'SILVER'), ('dbt_transform', 'JOB', 'TRANSFORM'),
        ('fact_revenue', 'TABLE', 'GOLD'), ('revenue_dashboard', 'DASHBOARD', 'BI')
    ]
    edges = [
        ('raw_salesforce', 'ingest_job'), ('ingest_job', 'stg_customers'),
        ('stg_customers', 'dbt_transform'), ('dbt_transform', 'fact_revenue'),
        ('fact_revenue', 'revenue_dashboard')
    ]
    for n in nodes:
        cur.execute(
            "INSERT INTO lineage_nodes VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", n)
    for e in edges:
        cur.execute(
            "INSERT INTO lineage_edges VALUES (%s, %s) ON CONFLICT DO NOTHING", e)


def generate_rich_history():
    print(f"🌱 Seeding Data into POSTGRES...")
    # UPDATED: Use centralized connection
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    setup_schema(cur)
    seed_lineage(cur)

    # --- 1. SEED FINANCIAL DATA (ZOMBIES) ---
    print("💰 Seeding Financial Audit Logs (4 Depts x 4 Job Types)...")
    audit_batch = []
    fingerprint_batch = {}

    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    current = start_date

    scenarios = [
        {"dept": "mktg", "base_cost": 0.5, "variance": 0.1,
            "freq": 80, "spike_prob": 0.01},
        {"dept": "eng",  "base_cost": 4.5, "variance": 1.5,
            "freq": 30,  "spike_prob": 0.20},
        {"dept": "ds",   "base_cost": 12.0, "variance": 3.0,
            "freq": 10,  "spike_prob": 0.15},
        {"dept": "fin",  "base_cost": 0.2, "variance": 0.05,
            "freq": 200, "spike_prob": 0.05}
    ]

    while current <= end_date:
        for scen in scenarios:
            daily_runs = random.randint(scen['freq'] - 5, scen['freq'] + 5)
            for _ in range(daily_runs):
                is_spike = random.random() < scen['spike_prob']
                cost = scen['base_cost'] * \
                    (random.uniform(5, 10) if is_spike else 1)
                severity = "HIGH" if cost > HIGH_SEVERITY_THRESHOLD else "LOW"

                lib = SCENARIO_LIBRARY.get(
                    scen['dept'], SCENARIO_LIBRARY['mktg'])
                scen_idx = random.randint(0, len(lib) - 1)
                task_id = f"{scen['dept']}_job_{scen_idx + 1}"

                audit_batch.append((
                    current, task_id, round(
                        cost, 2), severity, random.randint(30, 600)
                ))

                if task_id not in fingerprint_batch:
                    data = lib[scen_idx]
                    fingerprint_batch[task_id] = {
                        "count": 0, "total_cost": 0,
                        "bad": data['bad'], "fix": data['fix'], "diag": data['diag']
                    }
                fingerprint_batch[task_id]["count"] += 1
                fingerprint_batch[task_id]["total_cost"] += cost
        current += timedelta(minutes=random.randint(1400, 1480))

    args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s)", x).decode(
        'utf-8') for x in audit_batch)
    cur.execute(
        "INSERT INTO audit_events (timestamp, task_id, waste_usd, severity, duration_seconds) VALUES " + args_str)

    for task_id, stats in fingerprint_batch.items():
        avg_cost = stats["total_cost"] / stats["count"]
        cur.execute("""
            INSERT INTO query_fingerprints (hash_id, sql_text, optimized_sql_text, diagnosis_text, execution_count, avg_cost_usd)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """, (task_id, stats["bad"], stats["fix"], stats["diag"], stats["count"], round(avg_cost, 2)))

    # --- 2. SEED OBSERVABILITY DATA (PIPELINE RUNS) ---
    print(f"🚀 Seeding Pipeline Runs (Templates: {len(PIPELINE_TEMPLATES)})...")

    run_start = datetime.now() - timedelta(hours=24)
    while run_start <= datetime.now():
        jobs_to_run = random.sample(PIPELINE_TEMPLATES, k=random.randint(1, 3))

        for pipe in jobs_to_run:
            is_fail = random.random() < pipe['fail_prob']
            status = 'FAILED' if is_fail else 'SUCCESS'

            duration = pipe['base_dur'] * random.uniform(0.8, 1.5)
            rows = 0 if is_fail else int(random.uniform(1000, 50000))

            err_msg = pipe['error'] if is_fail else None
            stack = f"Traceback (most recent call last):\n  File 'pipeline.py', line 88, in process_batch\n    raise {err_msg}" if is_fail else None

            end_time = run_start + timedelta(seconds=duration)

            cur.execute("""
                INSERT INTO pipeline_runs (pipeline_name, start_time, end_time, duration_sec, status, rows_processed, throughput_rows_per_sec, error_message, stack_trace)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pipe['name'], run_start, end_time, round(
                    duration, 2), status, rows,
                round(rows/duration, 2) if duration > 0 else 0, err_msg, stack
            ))

        run_start += timedelta(minutes=random.randint(10, 20))

    conn.close()
    print("✅ Full Database Reset & Seed Complete.")


if __name__ == "__main__":
    generate_rich_history()
