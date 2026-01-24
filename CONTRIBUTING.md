# Contributing to Odos Auditor

Thank you for your interest in improving the Odos Auditor! We welcome contributions, especially those aimed at expanding our ecosystem of data connectors and infrastructure advisors.

## 🔌 Adding a New Data Connector

Odos is designed to be warehouse-agnostic. To add support for a new platform (e.g., Databricks, BigQuery), follow these steps:

### 1. Define the Fetcher

Create a new file in `odos/backend/connectors/`. Your class must implement the interface used by the `EnterpriseAuditor`.

```python
class NewWarehouseConnector:
    def fetch_attributed_costs(self, lookback_days: int) -> list[dict]:
        """
        Required Keys in returned dicts:
        - DAG_ID, TASK_ID, TRUE_COST_USD, DURATION_SEC, WAREHOUSE_NAME, fingerprint
        """
        pass
```

### 2. Update the Auditor Service

Register your new connector in `odos/backend/service.py` to allow EnterpriseAuditor to initialize with it.

### 3. Add Integration Tests

Add a mock version of your connector to `tests/conftest.py` and verify baseline establishment in `tests/integration/`.

## 🛠 Development Workflow

### Setup

Clone the repo and create a virtual environment:

```Bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create your `.env` file based on the template in the README.

Testing
We enforce a "Green Suite" policy. Before submitting a PR, ensure all unit tests pass:

```Bash
./run test
```

## 📜 Pull Request Guidelines

- Unit Tests: Every new feature must include unit tests in tests/unit/ using pytest-mock.
- Type Hinting: We use Python 3.12+ Type Parameter syntax (class Auditor[T]).
- Method Mapping: When adding methods to Surgeon, ensure they are reflected in the test suite method-discovery logic.
