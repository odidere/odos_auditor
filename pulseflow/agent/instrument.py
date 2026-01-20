import json
import logging
import threading
import uuid
from contextlib import contextmanager
from functools import wraps

import wrapt

logger = logging.getLogger("pulseflow.agent")
# Thread-local storage ensures metadata doesn't leak between concurrent tasks
_thread_context = threading.local()

try:
    import sqlglot
    from sqlglot import exp
    SQL_AVAILABLE = True
except ImportError:
    SQL_AVAILABLE = False
    logger.warning(
        "PulseFlow: sqlglot not found. SQL fingerprinting disabled.")


class SQLAnalyzer:
    """Enterprise SQL Parser with circuit breakers for safety."""
    @staticmethod
    def safe_analyze(sql_query: str):
        # PERFORMANCE GUARD: Skip analysis for massive queries to avoid latency
        if not SQL_AVAILABLE or len(sql_query) > 50000:
            # FIX: Return a explicit status so tests and logs can track the skip
            return {"status": "skipped", "reason": "size_limit_exceeded"}

        try:
            parsed = sqlglot.parse_one(sql_query)
            # CANONICALIZATION: Strip comments and normalize case so
            # 'SELECT *' and 'select *' produce the same fingerprint.
            canonical = parsed.sql(comments=False).lower()
            return {
                "status": "success",
                "fingerprint": str(abs(hash(canonical)) % (10**12)),
                "complexity": len(list(parsed.find_all(exp.Expression))),
                "tables": list(set(t.name for t in parsed.find_all(exp.Table)))
            }
        except Exception:
            # FAIL-SAFE: If parsing fails (unsupported syntax), return empty to keep running
            return {"status": "error", "fingerprint": "unknown"}


class PulseFlowContext:
    """Manages the telemetry state for the current execution thread."""
    @classmethod
    def set_context(cls, dag_id, task_id, run_id="manual"):
        _thread_context.trace_id = str(uuid.uuid4())
        _thread_context.dag_id = dag_id
        _thread_context.task_id = task_id
        _thread_context.run_id = run_id

    @classmethod
    def get_metadata(cls, analysis=None):
        ctx = {
            "trace_id": getattr(_thread_context, 'trace_id', str(uuid.uuid4())),
            "dag_id": getattr(_thread_context, 'dag_id', 'unknown'),
            "task_id": getattr(_thread_context, 'task_id', 'unknown'),
            "run_id": getattr(_thread_context, 'run_id', 'manual'),
            "ver": "2.1.0"
        }
        if analysis:
            ctx.update(analysis)
        return json.dumps(ctx)

# --- INTERFACE 1: CONTEXT MANAGER ---


@contextmanager
def pulse_trace(dag_id, task_id, run_id="manual"):
    """Usage: with pulse_trace('my_job', 'my_task'): ..."""
    try:
        PulseFlowContext.set_context(dag_id, task_id, run_id)
        yield
    finally:
        # Prevent context leakage into subsequent tasks in the same thread
        _thread_context.__dict__.clear()

# --- INTERFACE 2: DECORATOR ---


def pulse_audit(dag_id: str, task_id: str):
    """Usage: @pulse_audit('my_job', 'my_task') def run(): ..."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with pulse_trace(dag_id, task_id):
                return func(*args, **kwargs)
        return wrapper
    return decorator

# --- INTERFACE 3: MONKEY PATCHING (Zero-Touch) ---


def _pf_wrapper(wrapped, instance, args, kwargs):
    sql = args[0]
    try:
        # In 3.12, f-string parsing in get_metadata is pre-compiled for speed
        meta = PulseFlowContext.get_metadata(SQLAnalyzer.safe_analyze(sql))
        # Append metadata as a non-breaking SQL comment
        return wrapped(f"{sql}\n-- {meta}", *args[1:], **kwargs)
    except Exception as e:
        logger.error(f"PulseFlow Injection Error: {e}")
        return wrapped(*args, **kwargs)


def instrument_all():
    """Activates the global monkey patch for Snowflake."""
    import snowflake.connector.cursor
    if not hasattr(snowflake.connector.cursor.SnowflakeCursor.execute, '_pf'):
        wrapt.wrap_function_wrapper(
            'snowflake.connector.cursor',
            'SnowflakeCursor.execute',
            _pf_wrapper
        )
        snowflake.connector.cursor.SnowflakeCursor.execute._pf = True
