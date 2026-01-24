import json
import logging
import os
import traceback
import uuid
from functools import wraps

import psycopg2
import wrapt
# --- OPENTELEMETRY IMPORTS ---
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import \
    OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor,
                                            SimpleSpanProcessor, SpanExporter)
from opentelemetry.trace import Status, StatusCode

# --- SQL PARSING ---
try:
    import sqlglot
    from sqlglot import exp
    SQL_AVAILABLE = True
except ImportError:
    SQL_AVAILABLE = False

from odos.backend.config_loader import CONFIG
from odos.backend.db import get_db_connection  # <--- NEW IMPORT

logger = logging.getLogger("odos.agent")

# --- SETUP ---
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("odos.agent")
OBS_CONF = CONFIG.get('observability', {})

# --- EXPORTER 1: ODOS (Postgres) ---


class PulsePostgresExporter(SpanExporter):
    """Writes to Odos Postgres for Cost & Efficiency UI."""

    def __init__(self):
        pass  # Config handled by DB module

    def export(self, spans):
        conn = None
        try:
            conn = get_db_connection()
            conn.autocommit = True
            cur = conn.cursor()
            for span in spans:
                duration_sec = (span.end_time - span.start_time) / 1e9
                attrs = span.attributes or {}
                rows = attrs.get("db.rows_processed", 0)
                error_msg = attrs.get("error.message", None)
                stack_trace = attrs.get("error.stack_trace", None)
                throughput = rows / duration_sec if duration_sec > 0 else 0
                status_str = 'FAILED' if span.status.status_code == StatusCode.ERROR else 'SUCCESS'

                cur.execute("""
                    INSERT INTO pipeline_runs 
                    (pipeline_name, start_time, end_time, duration_sec, status, 
                     rows_processed, throughput_rows_per_sec, cpu_utilization_pct,
                     error_message, stack_trace)
                    VALUES (%s, TO_TIMESTAMP(%s), TO_TIMESTAMP(%s), %s, %s, %s, %s, %s, %s, %s)
                """, (
                    span.name, span.start_time/1e9, span.end_time/1e9,
                    duration_sec, status_str, rows, throughput, 0,
                    error_msg, stack_trace
                ))
            return list(map(lambda x: x.context.trace_id, spans))
        except Exception as e:
            # logger.error(f"Odos Export Failed: {e}")
            pass
        finally:
            if conn:
                conn.close()

    def shutdown(self): pass

# --- EXPORTER 2: LINEAGE (Graph) ---


class LineageExporter:
    """Writes Graph Nodes and Edges to Postgres."""

    def __init__(self):
        pass

    def _get_conn(self):
        return get_db_connection()

    def register_lineage(self, job_name, inputs, outputs, layer):
        try:
            conn = self._get_conn()
            conn.autocommit = True
            cur = conn.cursor()

            # A. Register JOB Node
            cur.execute("""
                INSERT INTO lineage_nodes (node_id, node_type, layer)
                VALUES (%s, 'JOB', %s)
                ON CONFLICT (node_id) DO UPDATE SET layer = EXCLUDED.layer
            """, (job_name, layer))

            # B. Register INPUTS (Source -> Job)
            for table in inputs:
                table_layer = 'RAW' if layer == 'ETL' else 'SILVER'
                cur.execute(
                    "INSERT INTO lineage_nodes (node_id, node_type, layer) VALUES (%s, 'TABLE', %s) ON CONFLICT DO NOTHING", (table, table_layer))
                cur.execute(
                    "INSERT INTO lineage_edges (source_node, target_node) VALUES (%s, %s) ON CONFLICT DO NOTHING", (table, job_name))

            # C. Register OUTPUTS (Job -> Target)
            for table in outputs:
                target_layer = 'SILVER' if layer == 'ETL' else 'GOLD'
                cur.execute(
                    "INSERT INTO lineage_nodes (node_id, node_type, layer) VALUES (%s, 'TABLE', %s) ON CONFLICT DO NOTHING", (table, target_layer))
                cur.execute(
                    "INSERT INTO lineage_edges (source_node, target_node) VALUES (%s, %s) ON CONFLICT DO NOTHING", (job_name, table))

            conn.close()
            logger.info(f"🕸️  Lineage captured for {job_name}")
        except Exception as e:
            logger.error(f"❌ Lineage Export Failed: {e}")


# --- REGISTER OTel EXPORTERS ---
if OBS_CONF.get('odos_export', True):
    trace.get_tracer_provider().add_span_processor(
        SimpleSpanProcessor(PulsePostgresExporter()))

if OBS_CONF.get('otlp_export', False):
    otlp_endpoint = OBS_CONF.get('otlp_endpoint', "http://localhost:4317")
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
    logger.info(f"✅ Odos: OTLP Export Active -> {otlp_endpoint}")

# --- SQL FINGERPRINTING & CONTEXT ---


class SQLAnalyzer:
    @staticmethod
    def safe_analyze(sql_query: str):
        if not SQL_AVAILABLE or len(sql_query) > 50000:
            return {}
        try:
            parsed = sqlglot.parse_one(sql_query)
            canonical = parsed.sql(comments=False).lower()
            return {
                "fingerprint": str(abs(hash(canonical)) % (10**12)),
                "complexity": len(list(parsed.find_all(exp.Expression))),
                "tables": list(set(t.name for t in parsed.find_all(exp.Table)))
            }
        except:
            return {}


class OdosContext:
    @classmethod
    def get_metadata(cls, analysis=None):
        span = trace.get_current_span()
        if span != trace.NonRecordingSpan(None):
            ctx_trace_id = f"{span.get_span_context().trace_id:032x}"
            mode = "pipeline"
        else:
            ctx_trace_id = str(uuid.uuid4())
            mode = "standalone"

        ctx = {"trace_id": ctx_trace_id, "mode": mode,
               "app": CONFIG['project']['name']}
        if analysis:
            ctx.update(analysis)
        return json.dumps(ctx)


def _pf_wrapper(wrapped, instance, args, kwargs):
    sql = args[0]
    try:
        meta = OdosContext.get_metadata(SQLAnalyzer.safe_analyze(sql))
        return wrapped(f"{sql}\n-- {meta}", *args[1:], **kwargs)
    except Exception:
        return wrapped(*args, **kwargs)


def auto_instrument():
    import snowflake.connector.cursor
    if not hasattr(snowflake.connector.cursor.SnowflakeCursor.execute, '_pf'):
        wrapt.wrap_function_wrapper(
            'snowflake.connector.cursor', 'SnowflakeCursor.execute', _pf_wrapper)
        snowflake.connector.cursor.SnowflakeCursor.execute._pf = True
        logger.info("✅ Odos: Snowflake Auto-Instrumentation Active")

# --- THE UNIFIED DECORATOR ---


def track_pipeline(name: str = None, inputs: list = [], outputs: list = [], layer: str = "ETL"):
    """
    The Single Source of Truth for:
    1. Pipeline Execution Logs (Start/End/Error)
    2. Data Lineage Graph (Source -> Job -> Target)
    3. SQL Cost Tracking (Auto-Instrumentation)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 1. Ensure SQL tagging is active
            auto_instrument()

            pipeline_name = name or func.__name__

            # 2. Capture Lineage (New Feature)
            if inputs or outputs:
                exporter = LineageExporter()
                exporter.register_lineage(
                    pipeline_name, inputs, outputs, layer)

            # 3. Track Execution (Observability)
            with tracer.start_as_current_span(pipeline_name) as span:
                try:
                    result = func(*args, **kwargs)
                    rows = result if isinstance(result, int) else 0
                    span.set_attribute("db.rows_processed", rows)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("error.message", str(e))
                    span.set_attribute("error.stack_trace",
                                       traceback.format_exc())
                    raise e
        return wrapper
    return decorator
