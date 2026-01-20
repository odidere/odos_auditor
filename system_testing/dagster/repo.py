import random

from dagster import job, op, repository

from pulseflow.agent.dagster_plugin import PulseFlowResource


# --- SCENARIO 1: The Good Citizen (Marketing) ---
@op(required_resource_keys={"pulseflow"})
def extract_marketing_data(context):
    """Consistent cost (~$0.50), predictable duration."""
    cost = round(random.uniform(0.5, 0.6), 2)
    context.resources.pulseflow.execute_query(
        "COPY INTO raw_marketing...", cost=cost, duration=12)


@job(resource_defs={"pulseflow": PulseFlowResource(conn_string="sqlite:////app/pulseflow.db")})
def marketing_pipeline():
    extract_marketing_data()

# --- SCENARIO 2: The Zombie (Engineering) ---


@op(required_resource_keys={"pulseflow"})
def train_model(context):
    """
    Volatile cost. 
    Normal: ~$5.00
    Anomaly (20% chance): ~$50.00 (10x Spike)
    """
    is_anomaly = random.random() < 0.2
    if is_anomaly:
        cost = round(random.uniform(45.0, 55.0), 2)
        query = "CALL train_model_v2() -- ANOMALY"
    else:
        cost = round(random.uniform(4.5, 5.5), 2)
        query = "CALL train_model_v2()"

    context.resources.pulseflow.execute_query(query, cost=cost, duration=60)


@job(resource_defs={"pulseflow": PulseFlowResource(conn_string="sqlite:////app/pulseflow.db")})
def engineering_pipeline():
    train_model()


@repository
def system_test_repo():
    return [marketing_pipeline, engineering_pipeline]
