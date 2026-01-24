from typing import Any

from sqlalchemy.orm import Session

from .advisor import WarehouseAdvisor
from .lineage import ImpactAnalyzer
from .models import AuditEvent, QueryFingerprint


class EnterpriseAuditor[T]:  # New Type Parameter Syntax
    def __init__(self, db: Session, sf_engine: T, lineage_edges: list[tuple[str, str]] | None = None):
        self.db = db
        self.sf = sf_engine
        self.lineage = ImpactAnalyzer(lineage_edges)

    def run_audit_cycle(self, lookback: int = 1) -> dict[str, Any]:
        """The core intelligence loop: Fetch -> Baseline -> Anomaly -> Advise."""
        logs = self.sf.fetch_attributed_costs(lookback)
        results = {"anomalies": [], "right_sizing": []}

        for log in logs:
            f_hash = log.get('fingerprint', 'unknown')
            cost = log['TRUE_COST_USD']

            # ATOMIC LOOKUP: Fetch or init the fingerprint baseline
            # Use .get() or .query() as per your SQLAlchemy version
            fp = self.db.get(QueryFingerprint, f_hash)

            if not fp:
                fp = QueryFingerprint(
                    hash_id=f_hash,
                    execution_count=0,  # Explicitly initialize
                    avg_cost_usd=0.0
                )
                self.db.add(fp)

            # FIX: Use getattr with a default or a simple (fp.execution_count or 0)
            # to prevent NoneType comparison errors.
            execution_count = fp.execution_count or 0
            avg_cost_usd = fp.avg_cost_usd or 0.0
            # STATISTICAL DRIFT: Cost > 3x historical baseline
            if execution_count > 5 and cost > (avg_cost_usd * 3):
                waste = cost - fp.avg_cost_usd
                event = AuditEvent(
                    fingerprint_id=f_hash, dag_id=log['DAG_ID'],
                    task_id=log['TASK_ID'], waste_usd=waste, severity="HIGH"
                )
                self.db.add(event)

                # ENRICHMENT: Blast Radius & SLA Delay
                results["anomalies"].append({
                    "task": log['TASK_ID'],
                    "waste": waste,
                    "blast_radius": self.lineage.calculate_blast_radius(log['TASK_ID']),
                    "delay_risk": self.lineage.get_critical_path_delay(log['TASK_ID'], log['DURATION_SEC'])
                })

            # EMA UPDATE: Exponential Moving Average for baseline
            alpha = 0.2
            if fp.execution_count > 0:
                fp.avg_cost_usd = (alpha * cost) + \
                    ((1 - alpha) * fp.avg_cost_usd)
            else:
                fp.avg_cost_usd = cost

            fp.execution_count += 1
            self.db.add(fp)

        # INFRASTRUCTURE ANALYSIS
        advisor = WarehouseAdvisor(logs)
        results["right_sizing"] = advisor.analyze_warehouse_efficiency()

        self.db.commit()
        return results
