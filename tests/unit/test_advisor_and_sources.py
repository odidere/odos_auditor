from datetime import datetime

import pytest

from odos.backend.advisor import WarehouseAdvisor, normalize_size
from odos.sources.base import CostRecord, WarehouseUsage
from odos.sources.bigquery import TIB, job_cost_usd, labels_to_dict
from odos.sources.mock import MockCostSource


def test_normalize_size():
    assert normalize_size("X-Small") == "X-SMALL"
    assert normalize_size("XSMALL") == "X-SMALL"
    assert normalize_size("2X-Large") == "2X-LARGE"
    assert normalize_size("weird") is None
    assert normalize_size(None) is None


def test_idle_and_downsize_recommendations():
    usage = [
        WarehouseUsage("BI_WH", "X-SMALL", 12.0, 3.0, 900, 2.0),     # 75% idle
        WarehouseUsage("ETL_WH", "LARGE", 40.0, 38.0, 400, 6.0),     # short queries on LARGE
        WarehouseUsage("OK_WH", "SMALL", 3.0, 2.8, 100, 30.0),       # fine
    ]
    recs = WarehouseAdvisor(usage, credit_price=3.0).recommendations()
    actions = {(r["warehouse"], r["action"]) for r in recs}
    assert actions == {("BI_WH", "REDUCE_IDLE"), ("ETL_WH", "DOWNSIZE")}
    idle = next(r for r in recs if r["action"] == "REDUCE_IDLE")
    assert idle["idle_cost_usd"] == pytest.approx(27.0)
    down = next(r for r in recs if r["action"] == "DOWNSIZE")
    assert down["suggested_size"] == "MEDIUM"


def test_cost_record_accepts_legacy_keys():
    r = CostRecord.from_mapping({"DAG_ID": "d", "TASK_ID": "t", "TRUE_COST_USD": 2.5,
                                 "DURATION_SEC": 10, "WAREHOUSE_NAME": "WH", "fingerprint": "sig1"})
    assert (r.dag_id, r.task_id, r.cost_usd, r.fingerprint, r.warehouse_name) == ("d", "t", 2.5, "sig1", "WH")


def test_cost_record_computes_fingerprint_from_text():
    a = CostRecord.from_mapping({"query_text": "SELECT 1 FROM t WHERE x = 5", "cost_usd": 1})
    b = CostRecord.from_mapping({"query_text": "select 1 from t where x = 9", "cost_usd": 1})
    assert a.fingerprint == b.fingerprint != "unknown"


def test_bigquery_cost_maths():
    assert job_cost_usd(TIB, None, False, 6.25, 0.06) == pytest.approx(6.25)
    assert job_cost_usd(None, 3_600_000 * 10, True, 6.25, 0.06) == pytest.approx(0.6)
    assert labels_to_dict([{"key": "odos_dag", "value": "d"}]) == {"odos_dag": "d"}


def test_snowflake_record_mapping_reads_query_tag():
    from odos.sources.snowflake import SnowflakeCostSource

    src = SnowflakeCostSource(connection=object(), credit_price=3.0)
    rec = src.to_record({
        "query_id": "q1", "query_parameterized_hash": "abc", "query_tag": '{"odos":1,"dag":"d","task":"t"}',
        "credits": 2.0, "duration_sec": 5.0, "start_time": datetime(2026, 1, 1), "warehouse_name": "WH",
        "warehouse_size": "Large", "query_text": "SELECT 1",
    })
    assert rec.cost_usd == pytest.approx(6.0)
    assert (rec.fingerprint, rec.dag_id, rec.task_id, rec.source) == ("abc", "d", "t", "snowflake")


def test_mock_source_is_deterministic_and_has_one_spike():
    now = datetime(2026, 1, 31)
    a = MockCostSource(now=now).fetch_attributed_costs()
    b = MockCostSource(now=now).fetch_attributed_costs()
    assert [r.cost_usd for r in a] == [r.cost_usd for r in b]
    finance = [r for r in a if r.dag_id == "finance_dag"]
    assert len({r.fingerprint for r in finance}) == 1
    assert finance[-1].cost_usd > 5 * finance[0].cost_usd


def test_timestamps_are_normalised_to_naive_utc():
    from datetime import timedelta, timezone

    lagos = timezone(timedelta(hours=1))
    r = CostRecord.from_mapping({"query_text": "SELECT 1", "cost_usd": 1,
                                 "start_time": datetime(2026, 1, 1, 10, 0, tzinfo=lagos)})
    assert r.start_time == datetime(2026, 1, 1, 9, 0)
    assert CostRecord.from_mapping({"cost_usd": 1, "start_time": "2026-01-01T09:00:00Z"}).start_time.tzinfo is None
