# Contributing to Odos Auditor

Contributions are welcome, especially new cost sources and advisor rules.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api,ai,snowflake]"
pytest -q
```

Tests run on SQLite with fake AI providers: no network, warehouse or API keys needed.

## Adding a cost source

A cost source turns a warehouse's query history into `CostRecord`s. Add a module under `odos/sources/`:

```python
from odos.sources.base import CostRecord


class DatabricksCostSource:
    name = "databricks"

    def fetch_attributed_costs(self, lookback_days: int = 1) -> list[CostRecord]:
        ...

    # Optional: enables idle-cost and right-sizing advice
    def fetch_warehouse_usage(self, lookback_days: int = 1): ...
```

Then register it in `odos/sources/__init__.py:build_source` and add tests that map raw rows to records (see `tests/unit/test_advisor_and_sources.py`).

Guidelines:

- **Fingerprints** must be stable across processes. Prefer the warehouse's own parameterised hash; otherwise use `odos.fingerprint.fingerprint`.
- **Cost** is USD per query run. Document how you calculate it and which prices come from config.
- **Least privilege:** document the minimum role or permissions the source needs.

## Pull requests

- Add tests for every behaviour change; keep tests offline.
- Anything sent to an LLM must go through `odos.backend.sql_safety` (redaction and validation).
- Odos must stay fail-open: instrumentation errors are logged, never raised into the user's pipeline.
