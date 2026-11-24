"""Warehouse right-sizing and idle-cost advice.

Uses billed (metered) credits versus credits attributed to queries. The gap is
idle time: a warehouse kept running between queries, mostly because of
``AUTO_SUSPEND`` settings and Snowflake's 60-second minimum each time a
warehouse resumes. (That minimum applies per resume, not per query.)
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from odos.sources.base import WarehouseUsage

SIZES = ["X-SMALL", "SMALL", "MEDIUM", "LARGE", "X-LARGE", "2X-LARGE",
         "3X-LARGE", "4X-LARGE", "5X-LARGE", "6X-LARGE"]
_SIZE_ALIASES = {"XSMALL": "X-SMALL", "XS": "X-SMALL", "S": "SMALL", "M": "MEDIUM", "L": "LARGE",
                 "XLARGE": "X-LARGE", "XL": "X-LARGE", "XXLARGE": "2X-LARGE", "2XLARGE": "2X-LARGE",
                 "3XLARGE": "3X-LARGE", "4XLARGE": "4X-LARGE"}


def normalize_size(size: str | None) -> str | None:
    if not size:
        return None
    key = size.upper().replace(" ", "").replace("_", "-")
    if key in SIZES:
        return key
    return _SIZE_ALIASES.get(key.replace("-", ""), None)


def smaller_size(size: str) -> str:
    return SIZES[max(0, SIZES.index(size) - 1)]


class WarehouseAdvisor:
    def __init__(self, usage: Iterable[WarehouseUsage], credit_price: float = 3.0,
                 settings: Mapping[str, Any] | None = None):
        self.usage = list(usage)
        self.credit_price = credit_price
        s = settings or {}
        self.idle_ratio_threshold = float(s.get("idle_ratio_threshold", 0.4))
        self.min_idle_cost_usd = float(s.get("min_idle_cost_usd", 5.0))
        self.downsize_max_avg_duration_sec = float(s.get("downsize_max_avg_duration_sec", 10.0))
        self.downsize_min_queries = int(s.get("downsize_min_queries", 50))

    def recommendations(self) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []
        for wh in self.usage:
            idle_cost = (wh.credits_metered - wh.credits_attributed) * self.credit_price
            if wh.idle_ratio >= self.idle_ratio_threshold and idle_cost >= self.min_idle_cost_usd:
                recs.append({
                    "warehouse": wh.warehouse_name,
                    "action": "REDUCE_IDLE",
                    "idle_ratio": round(wh.idle_ratio, 3),
                    "idle_cost_usd": round(idle_cost, 2),
                    "reason": (f"{wh.idle_ratio:.0%} of billed compute ran no queries. Lower AUTO_SUSPEND "
                               "(e.g. 60s) or batch small scheduled jobs onto fewer resumes."),
                })
            size = normalize_size(wh.warehouse_size)
            if (size and SIZES.index(size) >= SIZES.index("LARGE")
                    and wh.avg_duration_sec < self.downsize_max_avg_duration_sec
                    and wh.query_count >= self.downsize_min_queries):
                recs.append({
                    "warehouse": wh.warehouse_name,
                    "action": "DOWNSIZE",
                    "current_size": size,
                    "suggested_size": smaller_size(size),
                    "reason": (f"Average query takes {wh.avg_duration_sec:.1f}s on a {size} warehouse. "
                               "Test one size smaller: short queries rarely use the extra capacity."),
                    "note": "Estimate only. Compare runtime and credits on a test run before changing.",
                })
        return recs

    # Old method name kept for compatibility.
    def analyze_warehouse_efficiency(self) -> list[dict[str, Any]]:
        return self.recommendations()
