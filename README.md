# Odos Auditor

[![Odos CI (Unit Only)](https://github.com/odidere/odos_auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/odidere/odos_auditor/actions)

**Odos Auditor** is a high-performance observability and cost-governance engine designed for enterprise data platforms. It provides deep visibility into Snowflake credit consumption by bridging the gap between raw SQL execution and orchestration metadata.

By intercepting queries at the driver level, Odos identifies **"Zombie" tasks**, **Infrastructure Waste**, and **Downstream SLA Risks** with zero-to-minimal code changes.

---

## 🏗 System Architecture

Odos is designed with a "Fail-Open" philosophy, ensuring that observability never compromises production stability.

1.  **The Agent (Instrumentation):** Injects metadata into SQL comments and performs pre-flight AST analysis.
2.  **The Service (Intelligence):** Uses **SQLAlchemy 2.0** to manage high-concurrency state and calculate statistical baselines (EMA) for cost drift.
3.  **The Control Plane (UI):** A Streamlit-based dashboard for financial forecasting and remediation.
4.  **The Persistence:** A relational database (PostgreSQL/SQLite) storing normalized query fingerprints and lineage graphs.

---

## 🛠 Prerequisites & Environment

Odos leverages modern Python features (PEP 695) and requires:

- **Python:** 3.12+
- **Database:** PostgreSQL 15+ (Production) or SQLite (Dev)
- **Libraries:** `sqlalchemy>=2.0`, `sqlglot`, `pandas`, `fpdf2`, `openai`, `google-genai`

### Environment Configuration (`.env`)

Odos requires a `.env` file in the root directory for credential management:

```env
# Database
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=odos_observability
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# AI Intelligence (Required for optimize_sql)
OPENAI_API_KEY=sk-xxxx
GEMINI_API_KEY=AIzaSy-xxxx
```

## 🚀 Key Modules

### 1. Multi-Interface Agent (`odos.agent`)

- **Monkey Patching:** Global, zero-touch observability via `instrument_all()`.
- **Decorators:** Explicit function-level tracking via `@track_pipeline`.

### 2. AI Surgeon (`odos.backend.surgeon`)

The Surgeon module provides automated remediation for identified waste.

[Image of a software architecture diagram showing an AI agent fallback mechanism between OpenAI and Google Gemini]

- **`optimize_sql`**: Performs dual-model (OpenAI/Gemini) analysis to rewrite inefficient SQL.
- **`diagnose_pipeline_failure`**: Analyzes stack traces to identify root causes in real-time.

---

## 🚥 Quick Start & CLI

The `run` script is your master control center.

### Launch the Control Plane (UI)

```Bash
chmod +x run
./run ui
```

### Launch the API

```Bash

./run api
```

### Run the Test Suite

```Bash
./run test
```

## 🧪 Testing Strategy

Odos maintains a rigorous testing suite divided into two tiers:

### Unit Tests (`tests/unit/`)

- Math Logic: Validates Exponential Moving Average (EMA) and ROI calculations.
- Mocking: Uses pytest-mock to simulate Snowflake and AI provider responses, requiring no active API keys or live database.
- Execution: `pytest tests/unit/`

### Integration Tests (tests/integration/)

- Database: Validates SQLAlchemy 2.0 mappings against a live Postgres/SQLite instance.
- Intelligence: Verifies the EnterpriseAuditor can establish baselines and detect "Whale" cost spikes.
- Execution: `./run_tests.sh` (Auto-loads `.env`)

## 🛡 Security & Safety Guardrails

- Fail-Open Logic: If metadata injection fails, the original query executes unmodified.
- Performance Circuit Breaker: Queries exceeding 50KB bypass static analysis to prevent driver-side latency.
- Privacy: SQL is canonicalized (normalized) locally before being sent to AI providers for diagnosis.

### ⚙️ Configuration Files

`.github/workflows/ci.yml`

```
name: Odos CI (Unit Only)

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]

jobs:
  unit-tests:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pytest pytest-mock sqlalchemy pandas fpdf2 openai google-genai psycopg2-binary sqlglot

      - name: Make run script executable
        run: chmod +x run

      # Run unit tests only; these use mocks and don't require Postgres
      - name: Run Odos Unit Tests
        env:
          OPENAI_API_KEY: "sk-unit-test-fake-key"
          GEMINI_API_KEY: "gm-unit-test-fake-key"
        run: pytest tests/unit/
```

`run_tests.sh`

```
#!/bin/bash

# Load Environment Variables from .env
if [ -f .env ]; then
    echo "Reading .env file..."
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ Error: .env file not found. Ensure POSTGRES_PASSWORD is set for integration tests."
    exit 1
fi

# Set additional test-specific variables
export OPENAI_API_KEY=${OPENAI_API_KEY:-"sk-fake"}
export GEMINI_API_KEY=${GEMINI_API_KEY:-"gm-fake"}

echo "🧪 Running Odos Unit Tests..."
pytest tests/unit/

echo "🔗 Running Odos Integration Tests..."
pytest tests/integration/
```
