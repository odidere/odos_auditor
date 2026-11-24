"""Pipeline instrumentation.

* :func:`instrument_all` tags every Snowflake query with the current
  orchestration context through Snowflake's ``QUERY_TAG`` session parameter.
  The query text is never modified, so Snowflake's result cache keeps working.
* :func:`track_pipeline` records each pipeline run (duration, rows, errors) and
  optional lineage, and sets the context for the queries it runs.

Everything here is fail-open: if Odos cannot tag, trace or export, your query
or pipeline still runs exactly as it would without Odos.
"""
from __future__ import annotations

import functools
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from odos.agent.context import OdosContext
from odos.config import section
from odos.fingerprint import analyze

logger = logging.getLogger("odos.agent")

_PATCHED_ATTR = "_odos_original_execute"


# ---------------------------------------------------------------------------
# Query tagging
# ---------------------------------------------------------------------------
def _sync_query_tag(cursor: Any, original_execute: Callable) -> None:
    """Make the session's QUERY_TAG match the current context (one round trip
    only when the tag changes; nothing when there is no context)."""
    tag = OdosContext.query_tag()
    connection = getattr(cursor, "connection", None)
    holder = connection if connection is not None else cursor
    last = getattr(holder, "_odos_query_tag", None)
    if tag == (last or ""):
        return
    if tag:
        original_execute(cursor, "ALTER SESSION SET QUERY_TAG = %s", (tag,))
    else:
        # Only unset a tag that Odos itself set.
        original_execute(cursor, "ALTER SESSION UNSET QUERY_TAG")
    try:
        setattr(holder, "_odos_query_tag", tag or None)
    except Exception:
        pass


def instrument_cursor_class(cursor_cls: type) -> bool:
    """Patch ``cursor_cls.execute`` to keep QUERY_TAG in sync. Idempotent.

    Returns True if the class was patched by this call.
    """
    if getattr(cursor_cls, _PATCHED_ATTR, None) is not None:
        return False
    original = cursor_cls.execute

    @functools.wraps(original)
    def execute(self, *args, **kwargs):
        if section("observability").get("tag_mode", "query_tag") == "query_tag":
            try:
                _sync_query_tag(self, original)
            except Exception as exc:  # fail open: never block the user's query
                logger.debug("Odos: could not set QUERY_TAG (%s)", exc)
        return original(self, *args, **kwargs)

    setattr(cursor_cls, _PATCHED_ATTR, original)
    cursor_cls.execute = execute
    return True


def uninstrument_cursor_class(cursor_cls: type) -> None:
    original = getattr(cursor_cls, _PATCHED_ATTR, None)
    if original is not None:
        cursor_cls.execute = original
        delattr(cursor_cls, _PATCHED_ATTR)


def instrument_all() -> bool:
    """Enable Snowflake query tagging for this process. Safe to call repeatedly.

    Returns False when the Snowflake connector is not installed.
    """
    try:
        import snowflake.connector.cursor as sf_cursor
    except ImportError:
        logger.info("Odos: snowflake-connector-python not installed; tagging disabled")
        return False
    if instrument_cursor_class(sf_cursor.SnowflakeCursor):
        logger.info("Odos: Snowflake query tagging active")
    return True


# Old name kept for compatibility.
auto_instrument = instrument_all


class SQLAnalyzer:
    """Compatibility wrapper around :func:`odos.fingerprint.analyze`."""

    @staticmethod
    def safe_analyze(sql_query: str) -> dict:
        try:
            return analyze(sql_query)
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Tracing and run export
# ---------------------------------------------------------------------------
_tracer = None
_db_ready = False


def _ensure_db() -> None:
    """Create the Odos tables once per process before the agent writes to them."""
    global _db_ready
    if not _db_ready:
        from odos.backend.db import init_db

        init_db()
        _db_ready = True


def _record_run(values: dict[str, Any]) -> None:
    """Write one pipeline run to the Odos database (fail-open)."""
    if not section("observability").get("odos_export", True):
        return
    try:
        from odos.backend.db import session_scope
        from odos.backend.models import PipelineRun

        _ensure_db()
        with session_scope() as session:
            session.add(PipelineRun(**values))
    except Exception as exc:
        logger.warning("Odos: could not record pipeline run %s (%s)", values.get("pipeline_name"), exc)


def get_tracer():
    """Odos's own OpenTelemetry tracer (does not replace your global provider).

    Spans go to an OTLP collector when ``observability.otlp_export`` is true.
    Returns None when OpenTelemetry is not installed.
    """
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        return None
    provider = TracerProvider()
    obs = section("observability")
    if obs.get("otlp_export"):
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            endpoint = obs.get("otlp_endpoint", "http://localhost:4317")
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        except Exception as exc:
            logger.warning("Odos: OTLP export not available (%s)", exc)
    _tracer = provider.get_tracer("odos.agent")
    return _tracer


def register_lineage(job_name: str, inputs: Iterable[str], outputs: Iterable[str], layer: str = "ETL") -> None:
    """Record Source -> Job -> Target edges (fail-open, idempotent)."""
    try:
        from odos.backend.db import session_scope
        from odos.backend.models import LineageEdge, LineageNode

        def upsert_node(session, node_id, node_type, node_layer):
            node = session.get(LineageNode, node_id)
            if node is None:
                session.add(LineageNode(node_id=node_id, node_type=node_type, layer=node_layer))
            elif node_type == "JOB":
                node.layer = node_layer

        def add_edge(session, source, target):
            if session.get(LineageEdge, (source, target)) is None:
                session.add(LineageEdge(source_node=source, target_node=target))

        _ensure_db()
        with session_scope() as session:
            upsert_node(session, job_name, "JOB", layer)
            for table in inputs:
                upsert_node(session, table, "TABLE", "RAW" if layer == "ETL" else "SILVER")
                add_edge(session, table, job_name)
            for table in outputs:
                upsert_node(session, table, "TABLE", "SILVER" if layer == "ETL" else "GOLD")
                add_edge(session, job_name, table)
    except Exception as exc:
        logger.warning("Odos: lineage export failed for %s (%s)", job_name, exc)


def track_pipeline(
    name: str | None = None,
    inputs: Iterable[str] | None = None,
    outputs: Iterable[str] | None = None,
    layer: str = "ETL",
):
    """Decorator: records the run, tags its Snowflake queries and captures lineage.

    If the decorated function returns an ``int``, it is recorded as rows processed.
    """
    inputs = list(inputs or [])
    outputs = list(outputs or [])

    def decorator(func):
        pipeline_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            instrument_all()
            if inputs or outputs:
                register_lineage(pipeline_name, inputs, outputs, layer)

            existing = OdosContext.current()
            token = OdosContext.set_context(
                dag_id=existing.get("dag") or pipeline_name,
                task_id=existing.get("task") or func.__name__,
                run_id=existing.get("run"),
            )
            tracer = get_tracer()
            span_cm = tracer.start_as_current_span(pipeline_name) if tracer else None
            span = span_cm.__enter__() if span_cm else None
            started = datetime.now(timezone.utc).replace(tzinfo=None)
            t0 = time.perf_counter()
            status, error, stack, rows = "SUCCESS", None, None, 0
            try:
                result = func(*args, **kwargs)
                rows = result if isinstance(result, int) and not isinstance(result, bool) else 0
                return result
            except Exception as exc:
                status, error, stack = "FAILED", str(exc), traceback.format_exc()
                raise
            finally:
                duration = time.perf_counter() - t0
                trace_id = None
                if span is not None:
                    try:
                        span.set_attribute("db.rows_processed", rows)
                        if error:
                            from opentelemetry.trace import Status, StatusCode

                            span.set_status(Status(StatusCode.ERROR, error))
                        trace_id = f"{span.get_span_context().trace_id:032x}"
                    except Exception:
                        pass
                    span_cm.__exit__(None, None, None)
                ctx = OdosContext.current()
                OdosContext.clear(token)
                _record_run({
                    "pipeline_name": pipeline_name,
                    "dag_id": ctx.get("dag"),
                    "task_id": ctx.get("task"),
                    "run_id": ctx.get("run"),
                    "trace_id": trace_id,
                    "start_time": started,
                    "end_time": datetime.now(timezone.utc).replace(tzinfo=None),
                    "duration_sec": duration,
                    "status": status,
                    "rows_processed": rows,
                    "throughput_rows_per_sec": rows / duration if duration > 0 else 0.0,
                    "error_message": error,
                    "stack_trace": stack,
                })

        return wrapper

    return decorator
