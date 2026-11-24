# System testing (legacy)

These scripts predate the v0.2 schema. `seed_scenarios.py` and `seed_observability.py`
drop and recreate tables with the old layout, so do not run them against a database
that `odos init-db` created.

For a demo with the current schema, use:

```bash
odos init-db
odos audit --source mock --suggest   # --suggest needs OPENAI_API_KEY or GEMINI_API_KEY
odos ui
```

The Dagster/Grafana/OpenTelemetry setup here is still useful as a reference and will be
migrated to the new schema.
