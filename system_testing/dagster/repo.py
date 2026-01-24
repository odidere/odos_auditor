import os
import random
import time

import snowflake.connector
from dagster import ConfigurableResource, job, op, repository, resource
from pydantic import Field


# --- 1. DEFINE THE SNOWFLAKE RESOURCE ---
class SnowflakeResource(ConfigurableResource):
    user: str = Field(description="Snowflake User")
    password: str = Field(description="Snowflake Password")
    account: str = Field(
        description="Snowflake Account (e.g. xy12345.us-east-1)")
    warehouse: str = Field(
        description="Compute Warehouse", default="COMPUTE_WH")
    database: str = Field(description="Target Database",
                          default="PULSEFLOW_DEMO")
    schema_name: str = Field(description="Target Schema", default="RAW")

    def execute_query(self, sql: str):
        """Executes a query against Snowflake."""
        conn = snowflake.connector.connect(
            user=self.user,
            password=self.password,
            account=self.account,
            warehouse=self.warehouse,
            database=self.database,
            schema=self.schema_name
        )
        try:
            cur = conn.cursor()
            cur.execute(sql)
            return cur.fetchall()
        finally:
            conn.close()

# --- 2. DEFINE THE OPS (TASKS) ---


@op
def setup_environment(snowflake: SnowflakeResource):
    """Ensures the tables exist before we try to query them."""
    ddl = """
    CREATE TABLE IF NOT EXISTS RAW_MARKETING_DATA (id number, data varchar);
    CREATE TABLE IF NOT EXISTS RAW_ENGINEERING_LOGS (id number, log varchar);
    """
    # Split by semicolon to run multiple statements
    for stmt in ddl.split(";"):
        if stmt.strip():
            snowflake.execute_query(stmt)


@op
def extract_marketing_data(snowflake: SnowflakeResource):
    """
    Simulates a standard 'COPY INTO' or heavy SELECT.
    Cost: Low, Consistent.
    """
    # We simulate work by inserting rows.
    # In Snowflake, cost is time-based. We sleep to simulate execution time if we were observing real-time,
    # but for metadata generation, we just run the query.
    sql = "INSERT INTO RAW_MARKETING_DATA SELECT seq4(), 'dummy_data' FROM TABLE(GENERATOR(ROWCOUNT => 10000));"
    snowflake.execute_query(sql)


@op
def train_engineering_model(snowflake: SnowflakeResource):
    """
    The Zombie Task.
    Behavior: 20% chance of a "Full Table Scan" (Cartesian Join).
    """
    is_anomaly = random.random() < 0.2

    if is_anomaly:
        # THE ZOMBIE: A cross join that consumes compute credits
        # Warning: specific to Snowflake syntax
        query = """
        INSERT INTO RAW_ENGINEERING_LOGS 
        SELECT a.seq4(), 'anomaly' 
        FROM TABLE(GENERATOR(ROWCOUNT => 5000)) a, 
             TABLE(GENERATOR(ROWCOUNT => 500)) b
        """
    else:
        # Normal behavior
        query = "INSERT INTO RAW_ENGINEERING_LOGS SELECT seq4(), 'normal' FROM TABLE(GENERATOR(ROWCOUNT => 1000));"

    snowflake.execute_query(query)

# --- 3. DEFINE THE JOBS ---


@job
def marketing_pipeline():
    setup_environment()
    extract_marketing_data()


@job
def engineering_pipeline():
    setup_environment()
    train_engineering_model()

# --- 4. CONFIGURE THE REPO ---


@repository
def odos_snowflake_repo():
    return [
        marketing_pipeline.configured({
            "resources": {
                "snowflake": {
                    "config": {
                        "user": {"env": "SNOWFLAKE_USER"},
                        "password": {"env": "SNOWFLAKE_PASSWORD"},
                        "account": {"env": "SNOWFLAKE_ACCOUNT"},
                        "warehouse": {"env": "SNOWFLAKE_WAREHOUSE"},
                        "database": "PULSEFLOW_TEST_DB",
                        "schema_name": "RAW_DATA"
                    }
                }
            }
        }),
        engineering_pipeline.configured({
            "resources": {
                "snowflake": {
                    "config": {
                        "user": {"env": "SNOWFLAKE_USER"},
                        "password": {"env": "SNOWFLAKE_PASSWORD"},
                        "account": {"env": "SNOWFLAKE_ACCOUNT"},
                        "warehouse": {"env": "SNOWFLAKE_WAREHOUSE"},
                        "database": "PULSEFLOW_TEST_DB",
                        "schema_name": "RAW_DATA"
                    }
                }
            }
        })
    ]
