"""Common types for cost sources (Snowflake, BigQuery, mock)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from odos.fingerprint import fingerprint as compute_fingerprint

# Older code and tests used upper-case Snowflake-style keys.
_ALIASES = {
    "true_cost_usd": "cost_usd",
    "cost": "cost_usd",
    "dag": "dag_id",
    "task": "task_id",
    "run": "run_id",
    "query_hash": "fingerprint",
    "query_parameterized_hash": "fingerprint",
    "sql": "query_text",
}


def to_naive_utc(value: Any) -> datetime | None:
    """Warehouses return timezone-aware timestamps; Odos stores naive UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass
class CostRecord:
    """One query execution with its attributed cost."""

    query_id: str | None
    fingerprint: str
    cost_usd: float
    duration_sec: float = 0.0
    start_time: datetime | None = None
    warehouse_name: str | None = None
    warehouse_size: str | None = None
    dag_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    query_text: str | None = None
    bytes_scanned: int | None = None
    source: str = "unknown"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any], source: str = "unknown") -> "CostRecord":
        data: dict[str, Any] = {}
        for key, value in row.items():
            k = str(key).lower()
            data[_ALIASES.get(k, k)] = value
        text = data.get("query_text")
        fp = data.get("fingerprint") or (compute_fingerprint(text) if text else "unknown")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            query_id=data.get("query_id"),
            fingerprint=str(fp),
            cost_usd=float(data.get("cost_usd") or 0.0),
            duration_sec=float(data.get("duration_sec") or 0.0),
            start_time=to_naive_utc(data.get("start_time")),
            warehouse_name=data.get("warehouse_name"),
            warehouse_size=data.get("warehouse_size"),
            dag_id=data.get("dag_id"),
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
            query_text=text,
            bytes_scanned=data.get("bytes_scanned"),
            source=data.get("source") or source,
            extra=extra,
        )


@dataclass
class WarehouseUsage:
    """Billed vs. query-attributed compute for one warehouse/reservation."""

    warehouse_name: str
    warehouse_size: str | None
    credits_metered: float
    credits_attributed: float
    query_count: int
    avg_duration_sec: float

    @property
    def idle_ratio(self) -> float:
        if self.credits_metered <= 0:
            return 0.0
        return max(0.0, 1.0 - self.credits_attributed / self.credits_metered)


@runtime_checkable
class CostSource(Protocol):
    name: str

    def fetch_attributed_costs(self, lookback_days: int = 1) -> list[CostRecord]: ...


def normalize_records(rows: Iterable[Any], source: str = "unknown") -> list[CostRecord]:
    return [r if isinstance(r, CostRecord) else CostRecord.from_mapping(r, source) for r in rows]
