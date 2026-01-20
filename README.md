# PulseFlow Auditor: Phase 1 (The Auditor)

[![PulseFlow CI/CD](https://github.com/your-repo/pulseflow_auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/your-repo/pulseflow_auditor/actions)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](#)

**PulseFlow Auditor** is a high-performance observability and cost-governance engine designed for enterprise data platforms. It provides deep visibility into Snowflake credit consumption by bridging the gap between raw SQL execution and orchestration metadata.

By intercepting queries at the driver level, PulseFlow identifies **"Zombie" tasks**, **Infrastructure Waste**, and **Downstream SLA Risks** with zero-to-minimal code changes.

---

## 🏗 System Architecture

PulseFlow is designed with a "Fail-Open" philosophy, ensuring that observability never compromises production stability.

1.  **The Agent (Instrumentation):** Injects metadata into SQL comments and performs pre-flight AST analysis using `sqlglot`.
2.  **The Service (Intelligence):** Calculates statistical baselines (EMA) to detect cost drift and evaluates warehouse sizing.
3.  **The Control Plane (UI):** A Streamlit-based dashboard for financial forecasting and remediation.
4.  **The Persistence (Source of Truth):** A relational database storing query fingerprints, departmental budgets, and lineage graphs.

---

## 🚀 Key Modules

### 1. Multi-Interface Agent (`pulseflow.agent`)

Supports three distinct integration patterns:

- **Monkey Patching:** Global, zero-touch observability via `instrument_all()`.
- **Decorators:** Explicit function-level tracking via `@pulse_audit`.
- **Orchestrator Plugins:** Native hooks for **Apache Airflow** and **Dagster**.

### 2. SQL Structural Analyzer

Uses Abstract Syntax Tree (AST) parsing to:

- **Fingerprint Queries:** Normalizes SQL (removes comments/whitespace) to track the "DNA" of a query over time.
- **Complexity Scoring:** Identifies high-complexity logic running on under-powered warehouses.

### 3. Warehouse Right-Sizing Advisor (`pulseflow.backend.advisor`)

Implements two primary cost-saving signals:

- **Signal 1 (The Ferrari in Traffic):** High-tier warehouses (Large+) running sub-10s queries.
- **Signal 2 (The Idle Burner):** Warehouses with high costs but low query volume/concurrency.

### 4. Impact & SLA Analyzer (`pulseflow.backend.lineage`)

- **Blast Radius:** Identifies every downstream dashboard or ML model affected by an upstream anomaly.
- **Critical Path Delay:** Estimates SLA violation risks based on upstream duration increases.

---

## 🛠 Project Structure

```text
pulseflow_auditor/
├── pulseflow/
│   ├── agent/             # Instrumentation (Patching, Airflow Plugin, Dagster Resource)
│   ├── backend/           # Core Logic
│   │   ├── api.py         # FastAPI Endpoints
│   │   ├── ui.py          # Streamlit Dashboard
│   │   ├── service.py     # Auditor Intelligence
│   │   └── models.py      # SQLAlchemy Schema
├── tests/                 # Full Unit & Integration test suite
├── run.sh                 # Master CLI script (UI, API, Test, Docker)
├── docker-compose.yml     # Container Orchestration
└── requirements.txt       # Production dependencies
```

## 🚥 Quick Start & CLI

The run script is your master control center. It handles environment creation, database seeding, and execution.

1. Launch the Control Plane (UI)
   Start the developer dashboard to view costs and financial projections.

```Bash

chmod +x run.sh
./run ui
```

Access: http://localhost:8501

2. Launch the API
   Start the REST interface for automated auditing.

```Bash

./run.sh api
```

Access: http://localhost:8000/docs

3. Run the Test Suite
   Validate the logic with the full pytest suite.

```Bash

./run.sh test
```

4. Production Stack (Docker)
   Build and launch API, UI, and Grafana simultaneously.

```Bash

./run.sh docker
```

## 🔌 Integration Guide

Apache Airflow Integration
PulseFlow provides two ways to integrate with Airflow: a Drop-in Operator for specific tasks, or a Global Policy for platform-wide coverage.

Option A: The PulseFlow Operator (Drop-in)

```Python
from airflow import DAG
from pulseflow.agent.airflow_plugin import PulseFlowSnowflakeOperator

# Automatically tags queries with DAG_ID and TASK_ID
audit_task = PulseFlowSnowflakeOperator(
    task_id="calc_waste",
    sql="CALL calculate_daily_waste();",
    snowflake_conn_id="snowflake_default"
)
```

**Option B: Global Cluster Policy (Zero-Touch)** Instrument every Snowflake task in your Airflow environment by adding this to `airflow_local_settings.py`:

```Python

from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
from pulseflow.agent.instrument import PulseFlowContext

def task_policy(task):
    if isinstance(task, SnowflakeOperator):
        original_pre = task.pre_execute
        def pf_wrapper(context):
            PulseFlowContext.set_context(dag_id=task.dag_id, task_id=task.task_id)
            if original_pre: original_pre(context)
        task.pre_execute = pf_wrapper
```

### Dagster Integration

Use the PulseFlowResource to automatically instrument your assets.

```Python

from dagster import asset
from pulseflow.agent.dagster_plugin import PulseFlowResource

@asset
def raw_customers(context, pf: PulseFlowResource):
    # The resource automatically captures the asset key as the Task ID
    pf.execute_query("COPY INTO raw_customers FROM @stage/cust_data")
```

## 📊 Dashboard & Monitoring

Streamlit Control Plane (Dev)

- URL: http://localhost:8501
- Purpose: Financial forecasting, annual burn projection, and "Zombie" remediation.
- Key Metric: Infra-Tax Rate (Percentage of revenue spent on Snowflake).

Grafana (Production)

- URL: http://localhost:3000 (Default credentials: admin/admin)
- Data Source: SQLite (pulseflow.db)
- Purpose: Long-term alerts, severity trends, and NOC monitoring.

## 🛡 Security & Safety Guardrails

- Fail-Open Logic: If the metadata injection fails, the original query is executed unmodified.
- Performance Circuit Breaker: Queries exceeding 50KB bypass static analysis to prevent driver-side latency.
- Thread Isolation: Uses threading.local to ensure concurrent tasks (e.g., in Dagster/Airflow) do not leak metadata.
- Canonicalization: SQL is normalized to prevent redundant alerts for minor formatting changes.

📡 API Endpoints

| Endpoint                |  Method  | Description                                                     |
| :---------------------- | :------: | :-------------------------------------------------------------- |
| `/api/v1/audit/run`     | **POST** | Triggers a full audit cycle (Anomaly Detection + Right-sizing). |
| `/api/v1/audit/history` | **GET**  | Returns historical audit events with blast radius analysis.     |
| `/api/v1/infra/advisor` | **GET**  | Returns warehouse downsizing recommendations.                   |

## 🧪 Testing Suite

PulseFlow uses pytest for robust validation. The suite includes:

- Unit Tests: Validating SQL canonicalization and statistical EMA math.
- Integration Tests: End-to-end checks from agent injection to persistent DB state.

To run tests manually:

```Bash

export PYTHONPATH=$PYTHONPATH:.
pytest tests/ -v
```
