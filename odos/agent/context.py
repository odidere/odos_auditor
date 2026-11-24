"""Orchestration context (which DAG/task/run is executing right now).

Stored in a :class:`contextvars.ContextVar`, so it is isolated per thread and
per asyncio task and cannot leak between concurrent pipeline steps.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

QUERY_TAG_MAX_CHARS = 2000  # Snowflake's limit for QUERY_TAG
TAG_MARKER = "odos"

_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("odos_context", default=None)


def _current_trace_id() -> str | None:
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            return f"{span_context.trace_id:032x}"
    except Exception:
        pass
    return None


class OdosContext:
    """Set and read the orchestration context used to tag warehouse queries."""

    @staticmethod
    def set_context(
        dag_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> Token:
        """Set the context. Returns a token that :meth:`clear` can restore."""
        values: dict[str, Any] = {}
        merged_meta = dict(metadata or {})
        run_id = run_id or merged_meta.pop("run_id", None)
        for key, value in (("dag", dag_id), ("task", task_id), ("run", run_id)):
            if value is not None:
                values[key] = str(value)
        if merged_meta or extra:
            values["meta"] = {**merged_meta, **extra}
        return _CONTEXT.set(values)

    @staticmethod
    def clear(token: Token | None = None) -> None:
        if token is not None:
            _CONTEXT.reset(token)
        else:
            _CONTEXT.set(None)

    @staticmethod
    def current() -> dict[str, Any]:
        return dict(_CONTEXT.get() or {})

    @staticmethod
    @contextmanager
    def scope(**kwargs: Any) -> Iterator[None]:
        token = OdosContext.set_context(**kwargs)
        try:
            yield
        finally:
            OdosContext.clear(token)

    @staticmethod
    def query_tag() -> str:
        """JSON tag for the current context, or "" when there is none."""
        ctx = OdosContext.current()
        trace_id = _current_trace_id()
        if not ctx and not trace_id:
            return ""
        payload: dict[str, Any] = {TAG_MARKER: 1}
        payload.update({k: v for k, v in ctx.items() if k != "meta"})
        if trace_id:
            payload["trace"] = trace_id
        if ctx.get("meta"):
            payload["meta"] = ctx["meta"]
        tag = json.dumps(payload, separators=(",", ":"), default=str)
        if len(tag) > QUERY_TAG_MAX_CHARS:
            payload.pop("meta", None)
            tag = json.dumps(payload, separators=(",", ":"), default=str)[:QUERY_TAG_MAX_CHARS]
        return tag

    @staticmethod
    def bigquery_labels() -> dict[str, str]:
        """Context as BigQuery job labels (lower-case, max 63 chars, [a-z0-9_-])."""
        import re

        def clean(value: str) -> str:
            return re.sub(r"[^a-z0-9_-]", "_", str(value).lower())[:63]

        ctx = OdosContext.current()
        labels = {"odos": "1"}
        for key in ("dag", "task", "run"):
            if ctx.get(key):
                labels[f"odos_{key}"] = clean(ctx[key])
        return labels


def parse_query_tag(tag: str | None) -> dict[str, Any]:
    """Inverse of :meth:`OdosContext.query_tag`; returns {} for foreign tags."""
    if not tag:
        return {}
    try:
        payload = json.loads(tag)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict) or TAG_MARKER not in payload:
        return {}
    return payload
