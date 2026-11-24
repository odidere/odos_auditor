"""End-to-end flow on SQLite: audit -> anomaly -> AI suggestion -> human review."""
import json
from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy")

from odos.backend.models import AuditEvent, DailyCost, QueryFingerprint, Suggestion  # noqa: E402
from odos.backend.remediation import ReviewError, acceptance_rate, approve, generate_suggestions, reject  # noqa: E402
from odos.backend.service import EnterpriseAuditor  # noqa: E402
from odos.backend.surgeon import Surgeon  # noqa: E402
from odos.sources.mock import MockCostSource  # noqa: E402

NOW = datetime(2026, 1, 31, 12, 0)


class ListSource:
    name = "test"

    def __init__(self, rows):
        self.rows = rows

    def fetch_attributed_costs(self, lookback_days=1):
        return self.rows


def test_legacy_style_rows_still_work(db_session):
    db_session.add(QueryFingerprint(hash_id="sig1", avg_cost_usd=1.0, execution_count=10))
    db_session.commit()
    source = ListSource([{"DAG_ID": "test_dag_v1", "TASK_ID": "asset1", "TRUE_COST_USD": 10.0,
                          "DURATION_SEC": 500, "WAREHOUSE_NAME": "COMPUTE_WH", "fingerprint": "sig1"}])
    report = EnterpriseAuditor(db_session, source, [("asset1", "db_prod")]).run_audit_cycle()
    assert report["anomalies"][0]["waste"] == pytest.approx(9.0)
    assert report["anomalies"][0]["blast_radius"][0]["asset_id"] == "db_prod"


def test_mock_cycle_flags_the_spike_and_is_idempotent(db_session):
    source = MockCostSource(now=NOW)
    first = EnterpriseAuditor(db_session, source).run_audit_cycle()
    assert first["processed"] == 36
    assert [a["dag"] for a in first["anomalies"]] == ["finance_dag"]
    assert {r["action"] for r in first["right_sizing"]} >= {"REDUCE_IDLE"}

    second = EnterpriseAuditor(db_session, source).run_audit_cycle()
    assert second["processed"] == 0 and second["skipped"] == 36
    assert db_session.query(AuditEvent).count() == 1
    total = sum(d.cost_usd for d in db_session.query(DailyCost).all())
    assert total == pytest.approx(sum(r.cost_usd for r in source.fetch_attributed_costs()))


def test_fingerprint_sample_is_redacted(db_session):
    EnterpriseAuditor(db_session, MockCostSource(now=NOW)).run_audit_cycle()
    samples = [fp.sql_sample for fp in db_session.query(QueryFingerprint).all()]
    assert samples and all("2026" not in s for s in samples)


def test_suggestion_lifecycle(db_session, fake_provider_cls, tmp_path):
    EnterpriseAuditor(db_session, MockCostSource(now=NOW)).run_audit_cycle()
    response = {"diagnosis": "Selects every column of both tables.",
                "suggested_sql": "SELECT o.id, p.amount FROM analytics.orders o JOIN analytics.payments p ON o.id = p.order_id",
                "strategy": "Column pruning", "estimated_savings_pct": 35}
    surgeon = Surgeon(providers=[fake_provider_cls("openai", [response])])

    created = generate_suggestions(db_session, surgeon)
    assert len(created) == 1 and created[0].status == "PENDING"
    assert generate_suggestions(db_session, surgeon) == []  # no duplicate for the same event

    approved = approve(db_session, created[0].id, "shina", "Looks right")
    assert approved.status == "APPROVED" and approved.decided_by == "shina"
    with pytest.raises(ReviewError):
        reject(db_session, created[0].id, "shina")
    log = [json.loads(line) for line in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    assert log[-1]["decision"] == "APPROVED"
    assert acceptance_rate(db_session)["fake-1"]["rate"] == 1.0


def test_failed_ai_is_recorded_not_hidden(db_session, fake_provider_cls):
    EnterpriseAuditor(db_session, MockCostSource(now=NOW)).run_audit_cycle()
    surgeon = Surgeon(providers=[fake_provider_cls("openai", [RuntimeError("timeout")])])
    created = generate_suggestions(db_session, surgeon)
    assert created[0].status == "FAILED"
    with pytest.raises(ReviewError):
        approve(db_session, created[0].id, "shina")
    assert db_session.query(Suggestion).count() == 1
