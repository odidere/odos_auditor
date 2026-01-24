import os

import snowflake.connector

# Configuration
DB_NAME = "ODOS_TEST_DB"
SCHEMA_NAME = "RAW_DATA"
WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")


def get_snowflake_conn():
    """Connects using the same env vars as the main app."""
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=WAREHOUSE,
        role=os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
    )


def provision_test_environment():
    print(f"❄️  Provisioning Real Snowflake Assets in {DB_NAME}...")

    if not os.getenv("SNOWFLAKE_ACCOUNT"):
        print("⚠️  Skipping: SNOWFLAKE_ACCOUNT env var not set.")
        return

    conn = get_snowflake_conn()
    cur = conn.cursor()

    try:
        # 1. Setup Database Context
        print("   - Creating Database & Schema...")
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_NAME}.{SCHEMA_NAME}")
        cur.execute(f"USE SCHEMA {DB_NAME}.{SCHEMA_NAME}")

        # 2. Create "Ghost Table" Candidate
        # Matches logic: Not queried recently, > 1KB size
        print("   - Creating 'Ghost Table' candidate (LEGACY_MARKETING_LOGS_2024)...")
        cur.execute("""
            CREATE OR REPLACE TABLE LEGACY_MARKETING_LOGS_2024 (
                id NUMBER, 
                payload VARCHAR(16777216), 
                ingested_at TIMESTAMP
            )
        """)
        # Insert ~5MB of dummy data to ensure it registers in storage metrics
        cur.execute("""
            INSERT INTO LEGACY_MARKETING_LOGS_2024 
            SELECT seq4(), randstr(100, random()), DATEADD(day, -100, CURRENT_TIMESTAMP()) 
            FROM TABLE(GENERATOR(ROWCOUNT => 10000))
        """)

        # 3. Create "Cold Data" Candidate
        # Matches logic: Name contains 'HISTORY', data > 1 year old
        print("   - Creating 'Cold Data' candidate (WEB_EVENTS_HISTORY)...")
        cur.execute("""
            CREATE OR REPLACE TABLE WEB_EVENTS_HISTORY (
                user_id VARCHAR, 
                event_type VARCHAR, 
                event_ts TIMESTAMP
            )
        """)
        # Simulate data from 2 years ago
        cur.execute("""
            INSERT INTO WEB_EVENTS_HISTORY 
            SELECT 'u_' || seq4(), 'click', DATEADD(year, -2, CURRENT_TIMESTAMP()) 
            FROM TABLE(GENERATOR(ROWCOUNT => 10000))
        """)

        # 4. Create "Unclustered" Candidate
        # Matches logic: High scan rate (we simulate this by having no clustering key)
        print("   - Creating 'Clustering' candidate (RAW_SENSOR_STREAM)...")
        cur.execute("""
            CREATE OR REPLACE TABLE RAW_SENSOR_STREAM (
                sensor_id INTEGER, 
                reading FLOAT, 
                recorded_at TIMESTAMP
            )
        """)
        cur.execute("""
            INSERT INTO RAW_SENSOR_STREAM 
            SELECT seq4(), uniform(1.0, 100.0, random()), CURRENT_TIMESTAMP() 
            FROM TABLE(GENERATOR(ROWCOUNT => 10000))
        """)

        print("✅ Snowflake Provisioning Complete.")
        print(f"   Target: {DB_NAME}.{SCHEMA_NAME}")
        print("   NOTE: Snowflake Metadata Views (ACCOUNT_USAGE) have a latency of 45-90 minutes.")
        print("   The Storage Advisor will detect these tables after the next Snowflake metadata sync.")

    except Exception as e:
        print(f"❌ Provisioning Failed: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    provision_test_environment()
