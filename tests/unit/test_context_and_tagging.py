import json

from odos.agent.context import QUERY_TAG_MAX_CHARS, OdosContext, parse_query_tag
from odos.agent.instrument import SQLAnalyzer, instrument_cursor_class, uninstrument_cursor_class


def test_context_set_and_clear():
    token = OdosContext.set_context(dag_id="d", task_id="t", run_id="r1")
    assert OdosContext.current() == {"dag": "d", "task": "t", "run": "r1"}
    OdosContext.clear(token)
    assert OdosContext.current() == {}


def test_scope_restores_outer_context():
    with OdosContext.scope(dag_id="outer"):
        with OdosContext.scope(dag_id="inner", task_id="x"):
            assert OdosContext.current()["dag"] == "inner"
        assert OdosContext.current() == {"dag": "outer"}
    assert OdosContext.current() == {}


def test_query_tag_round_trip_and_limit():
    assert OdosContext.query_tag() == ""
    with OdosContext.scope(dag_id="d", task_id="t", metadata={"orchestrator": "airflow"}):
        tag = OdosContext.query_tag()
        assert parse_query_tag(tag)["task"] == "t"
    with OdosContext.scope(dag_id="d", metadata={"blob": "x" * 5000}):
        assert len(OdosContext.query_tag()) <= QUERY_TAG_MAX_CHARS
    assert parse_query_tag('{"app": "someone else"}') == {}
    assert parse_query_tag("not json") == {}


def test_bigquery_labels_are_valid():
    with OdosContext.scope(dag_id="Finance DAG!", task_id="Build.Revenue"):
        labels = OdosContext.bigquery_labels()
    assert labels == {"odos": "1", "odos_dag": "finance_dag_", "odos_task": "build_revenue"}


class FakeConnection:
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self


def test_tagging_sets_query_tag_once_and_never_changes_query_text():
    instrument_cursor_class(FakeCursor)
    try:
        cursor = FakeCursor(FakeConnection())
        cursor.execute("SELECT 1")  # no context: no tag statement
        with OdosContext.scope(dag_id="d", task_id="t"):
            cursor.execute("SELECT 2")
            cursor.execute("SELECT 3")  # same tag: no extra round trip
        cursor.execute("SELECT 4")      # context gone: tag removed
        statements = [s for s, _ in cursor.executed]
        assert statements[0] == "SELECT 1"
        assert statements[1] == "ALTER SESSION SET QUERY_TAG = %s"
        assert json.loads(cursor.executed[1][1][0])["task"] == "t"
        assert statements[2:4] == ["SELECT 2", "SELECT 3"]
        assert statements[4] == "ALTER SESSION UNSET QUERY_TAG"
        assert statements[5] == "SELECT 4"
    finally:
        uninstrument_cursor_class(FakeCursor)


def test_tagging_fails_open():
    class BrokenTagCursor(FakeCursor):
        def execute(self, sql, params=None):
            if sql.startswith("ALTER SESSION"):
                raise RuntimeError("no permission")
            return super().execute(sql, params)

    instrument_cursor_class(BrokenTagCursor)
    try:
        cursor = BrokenTagCursor(FakeConnection())
        with OdosContext.scope(dag_id="d"):
            cursor.execute("SELECT 1")
        assert cursor.executed == [("SELECT 1", None)]
    finally:
        uninstrument_cursor_class(BrokenTagCursor)


def test_instrumenting_twice_is_a_no_op():
    assert instrument_cursor_class(FakeCursor) is True
    try:
        assert instrument_cursor_class(FakeCursor) is False
    finally:
        uninstrument_cursor_class(FakeCursor)


def test_sql_analyzer_compat():
    result = SQLAnalyzer.safe_analyze("SELECT * FROM t WHERE a = 1")
    assert set(result) == {"fingerprint", "tables", "complexity"}
    assert SQLAnalyzer.safe_analyze("") == {}


def test_track_pipeline_sets_context_and_fails_open(monkeypatch):
    from odos.agent import instrument

    recorded = []
    monkeypatch.setattr(instrument, "_record_run", recorded.append)
    monkeypatch.setattr(instrument, "instrument_all", lambda: False)
    seen = {}

    @instrument.track_pipeline(name="nightly_orders")
    def job():
        seen.update(OdosContext.current())
        return 42

    assert job() == 42
    assert seen == {"dag": "nightly_orders", "task": "job"}
    assert OdosContext.current() == {}
    assert recorded[0]["status"] == "SUCCESS" and recorded[0]["rows_processed"] == 42

    @instrument.track_pipeline()
    def broken():
        raise ValueError("boom")

    import pytest
    with pytest.raises(ValueError):
        broken()
    assert recorded[1]["status"] == "FAILED" and "boom" in recorded[1]["error_message"]


def test_record_run_never_raises(monkeypatch):
    from odos.agent import instrument

    def explode():
        raise RuntimeError("db down")

    monkeypatch.setattr(instrument, "_ensure_db", explode)
    instrument._record_run({"pipeline_name": "x"})  # logs a warning, does not raise
