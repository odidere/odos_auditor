"""Deterministic demo data: steady pipelines plus one cost spike and an idle warehouse."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from odos.sources.base import CostRecord, WarehouseUsage

DEMO_QUERIES = [
    ("marketing_dag", "load_campaigns", "LOAD_WH_SMALL",
     "SELECT campaign_id, SUM(spend) FROM raw.ad_spend WHERE day = '2026-01-01' GROUP BY 1", 0.40),
    ("finance_dag", "build_revenue", "TRANSFORM_WH_LARGE",
     "SELECT * FROM analytics.orders o JOIN analytics.payments p ON o.id = p.order_id", 2.50),
    ("ops_dag", "refresh_sla", "BI_WH_XSMALL",
     "SELECT warehouse_id, AVG(minutes) FROM ops.deliveries WHERE day >= '2026-01-01' GROUP BY 1", 0.15),
]


class MockCostSource:
    """Generates ``runs`` executions per query; the last finance run spikes 8x."""

    name = "mock"

    def __init__(self, runs: int = 12, seed: int = 7, spike_multiplier: float = 8.0,
                 now: datetime | None = None):
        self.runs = runs
        self.seed = seed
        self.spike_multiplier = spike_multiplier
        self.now = now or datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    def fetch_attributed_costs(self, lookback_days: int = 1) -> list[CostRecord]:
        rng = random.Random(self.seed)
        start = self.now - timedelta(days=lookback_days)
        step = timedelta(days=lookback_days) / max(self.runs, 1)
        records = []
        for i in range(self.runs):
            for dag, task, warehouse, sql, base_cost in DEMO_QUERIES:
                cost = base_cost * rng.uniform(0.9, 1.1)
                if dag == "finance_dag" and i == self.runs - 1:
                    cost *= self.spike_multiplier
                records.append(CostRecord.from_mapping({
                    "query_id": f"mock-{dag}-{i}",
                    "query_text": sql.replace("2026-01-01", f"2026-01-{(i % 28) + 1:02d}"),
                    "cost_usd": round(cost, 4),
                    "duration_sec": round(cost * 40, 1),
                    "start_time": start + step * i,
                    "warehouse_name": warehouse,
                    "warehouse_size": warehouse.rsplit("_", 1)[-1].replace("XSMALL", "X-SMALL"),
                    "dag_id": dag,
                    "task_id": task,
                    "run_id": f"run-{i}",
                }, source=self.name))
        return records

    def fetch_warehouse_usage(self, lookback_days: int = 1) -> list[WarehouseUsage]:
        return [
            WarehouseUsage("LOAD_WH_SMALL", "SMALL", 3.0, 2.6, 120, 35.0),
            WarehouseUsage("TRANSFORM_WH_LARGE", "LARGE", 40.0, 30.0, 400, 6.0),
            WarehouseUsage("BI_WH_XSMALL", "X-SMALL", 12.0, 3.0, 900, 2.0),
        ]
