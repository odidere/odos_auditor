"""Configuration for Odos.

Loading is lazy and falls back to defaults, so importing any Odos module never
fails because a config file is missing. Lookup order for the YAML file:

1. the path in the ``ODOS_CONFIG`` environment variable
2. ``config.yaml`` in the current working directory
3. ``config.yaml`` at the repository root (next to the ``odos`` package)

Values in the file are deep-merged over :data:`DEFAULTS`.
"""
from __future__ import annotations

import copy
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("odos.config")

DEFAULTS: dict[str, Any] = {
    "project": {"name": "Odos Auditor", "company_name": "Odos"},
    "app": {"budget_cap": 5000},
    # DATABASE_URL (env) wins over database.url, which wins over POSTGRES_* env vars.
    "database": {"url": None},
    "source": {"type": "mock", "lookback_days": 1, "bigquery_region": "us"},
    "observability": {
        "odos_export": True,
        "otlp_export": False,
        "otlp_endpoint": "http://localhost:4317",
        # "query_tag" sets Snowflake's QUERY_TAG; "off" disables tagging.
        "tag_mode": "query_tag",
    },
    "costs": {
        "compute_credit_price": 3.00,       # USD per Snowflake credit
        "storage_price_per_tb_mo": 23.00,   # USD per TB per month
        "bigquery_price_per_tib": 6.25,     # USD per TiB billed (on-demand)
        "bigquery_slot_hour_price": 0.06,   # USD per slot-hour (Editions)
    },
    "detection": {
        "min_runs": 5,            # runs needed before a fingerprint can be flagged
        "ratio_threshold": 3.0,   # flag when cost > ratio x baseline ...
        "deviation_k": 4.0,       # ... and > baseline + k x typical deviation
        "min_waste_usd": 1.0,     # ignore spikes that cost less than this
        "alpha": 0.2,             # smoothing factor for the moving baseline
    },
    "ai": {
        "enabled": True,
        "max_suggestions_per_cycle": 10,
        "timeout_sec": 30,
        "max_output_tokens": 1500,
        "openai_model": "gpt-4.1-mini",
        "gemini_model": "gemini-2.5-flash",
        # When false, string and number literals are replaced by placeholders
        # before any SQL leaves your environment.
        "send_literals": False,
        "dialect": "snowflake",
    },
    "advisor": {
        "idle_ratio_threshold": 0.4,
        "min_idle_cost_usd": 5.0,
        "downsize_max_avg_duration_sec": 10.0,
        "downsize_min_queries": 50,
    },
    "rules": {
        "ghost_tables": {"days_since_last_access": 90, "min_size_bytes": 1073741824},
        "cold_data": {
            "min_data_age_days": 365,
            "min_size_bytes": 1099511627776,
            "target_tables_regex": ".*(LOG|EVENT|HISTORY).*",
        },
        "clustering": {"min_scan_ratio": 0.9, "min_size_bytes": 10737418240, "min_partitions": 100},
    },
    "security": {"auth_enabled": True},
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def config_path() -> Path | None:
    candidates = []
    if os.getenv("ODOS_CONFIG"):
        candidates.append(Path(os.environ["ODOS_CONFIG"]))
    candidates.append(Path.cwd() / "config.yaml")
    candidates.append(Path(__file__).resolve().parent.parent / "config.yaml")
    for path in candidates:
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the merged configuration (cached; see :func:`reload_config`)."""
    path = config_path()
    if path is None:
        logger.info("Odos: no config.yaml found, using defaults")
        return copy.deepcopy(DEFAULTS)
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except Exception as exc:  # malformed file or PyYAML missing
        logger.warning("Odos: could not read %s (%s); using defaults", path, exc)
        loaded = {}
    return _deep_merge(DEFAULTS, loaded)


def reload_config() -> dict[str, Any]:
    get_config.cache_clear()
    return get_config()


def section(name: str) -> dict[str, Any]:
    return get_config().get(name, {}) or {}
