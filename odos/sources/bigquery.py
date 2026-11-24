"""BigQuery cost source, from ``INFORMATION_SCHEMA.JOBS_BY_PROJECT``.

Cost per job:

* on-demand jobs: ``total_bytes_billed`` x price per TiB
* jobs on a reservation (Editions): ``total_slot_ms`` x price per slot-hour

Set both prices in ``costs`` in config.yaml to match your contract. To attribute
jobs to pipelines, pass ``OdosContext.bigquery_labels()`` as job labels.
"""
from __future__ import annotations

import re
from typing import Any

from odos.config import section
from odos.sources.base import CostRecord

TIB = 1024 ** 4
_REGION = re.compile(r"^[a-z0-9-]+$")

JOBS_SQL = """
SELECT
  job_id,
  query,
  labels,
  reservation_id,
  total_bytes_billed,
  total_bytes_processed,
  total_slot_ms,
  start_time,
  TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) / 1000.0 AS duration_sec,
  query_info.query_hashes.normalized_literals AS normalized_hash
FROM `region-{region}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback DAY)
  AND job_type = 'QUERY'
  AND state = 'DONE'
  AND statement_type != 'SCRIPT'
  AND error_result IS NULL
ORDER BY start_time
"""


def job_cost_usd(total_bytes_billed: int | None, total_slot_ms: int | None, on_reservation: bool,
                 price_per_tib: float, slot_hour_price: float) -> float:
    if on_reservation:
        return (total_slot_ms or 0) / 3_600_000 * slot_hour_price
    return (total_bytes_billed or 0) / TIB * price_per_tib


def labels_to_dict(labels: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in labels or []:
        key = item.get("key") if isinstance(item, dict) else getattr(item, "key", None)
        value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
        if key:
            result[key] = value
    return result


class BigQueryCostSource:
    name = "bigquery"

    def __init__(self, client: Any = None, region: str | None = None, project: str | None = None):
        self._client = client
        self.project = project
        self.region = (region or section("source").get("bigquery_region", "us")).lower()
        if not _REGION.match(self.region):
            raise ValueError(f"Invalid BigQuery region: {self.region!r}")
        costs = section("costs")
        self.price_per_tib = float(costs.get("bigquery_price_per_tib", 6.25))
        self.slot_hour_price = float(costs.get("bigquery_slot_hour_price", 0.06))

    @property
    def client(self):
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=self.project)
        return self._client

    def fetch_attributed_costs(self, lookback_days: int = 1) -> list[CostRecord]:
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("lookback", "INT64", int(lookback_days))],
            labels={"odos": "1", "odos_task": "cost_audit"},
        )
        rows = self.client.query(JOBS_SQL.format(region=self.region), job_config=job_config).result()
        return [self.to_record(dict(row.items())) for row in rows]

    def to_record(self, row: dict[str, Any]) -> CostRecord:
        labels = labels_to_dict(row.get("labels"))
        cost = job_cost_usd(row.get("total_bytes_billed"), row.get("total_slot_ms"),
                            bool(row.get("reservation_id")), self.price_per_tib, self.slot_hour_price)
        return CostRecord.from_mapping({
            "query_id": row.get("job_id"),
            "fingerprint": row.get("normalized_hash"),
            "query_text": row.get("query"),
            "cost_usd": cost,
            "duration_sec": row.get("duration_sec"),
            "start_time": row.get("start_time"),
            "warehouse_name": row.get("reservation_id") or "on-demand",
            "bytes_scanned": row.get("total_bytes_processed"),
            "dag_id": labels.get("odos_dag"),
            "task_id": labels.get("odos_task"),
            "run_id": labels.get("odos_run"),
        }, source=self.name)
