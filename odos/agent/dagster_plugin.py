"""Dagster integration.

Add ``OdosResource`` to your Definitions to enable tagging for the run, then
wrap step code in ``odos_step(context)`` to attribute queries to the op/asset::

    @asset
    def orders(context, odos: OdosResource):
        with odos.step(context):
            run_snowflake_queries()
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from dagster import ConfigurableResource, InitResourceContext

from odos.agent.context import OdosContext
from odos.agent.instrument import instrument_all


def _step_name(context: Any) -> str | None:
    for attr in ("asset_key", "op_def", "op"):
        value = getattr(context, attr, None)
        if value is None:
            continue
        if hasattr(value, "to_user_string"):
            return value.to_user_string()
        if hasattr(value, "name"):
            return value.name
    return None


@contextmanager
def odos_step(context: Any) -> Iterator[None]:
    """Attribute queries inside the block to this Dagster op or asset."""
    run = getattr(context, "run", None) or getattr(context, "dagster_run", None)
    with OdosContext.scope(
        dag_id=getattr(run, "job_name", None) or "dagster",
        task_id=_step_name(context),
        run_id=getattr(context, "run_id", None),
        metadata={"orchestrator": "dagster"},
    ):
        yield


class OdosResource(ConfigurableResource):
    """Enables Snowflake query tagging for the run (Dagster 1.6+)."""

    def setup_for_execution(self, context: InitResourceContext) -> None:
        instrument_all()
        run = context.dagster_run
        OdosContext.set_context(
            dag_id=run.job_name if run else "dagster",
            run_id=context.run_id,
            metadata={"orchestrator": "dagster"},
        )

    def step(self, context: Any):
        return odos_step(context)
