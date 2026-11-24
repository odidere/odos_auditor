"""Airflow integration.

``OdosSnowflakeOperator`` is a drop-in replacement for ``SnowflakeOperator``
(or ``SQLExecuteQueryOperator`` on newer providers) that tags every query it
runs with the DAG id, task id and run id.
"""
from __future__ import annotations

from typing import Any

from odos.agent.context import OdosContext
from odos.agent.instrument import instrument_all

try:  # apache-airflow-providers-snowflake < 6
    from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator as _BaseOperator
except ImportError:  # newer providers: use the generic SQL operator
    from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator as _BaseOperator


def airflow_context_kwargs(context: Any) -> dict[str, Any]:
    ti = context.get("ti") or context.get("task_instance")
    return {
        "dag_id": getattr(ti, "dag_id", None) or getattr(context.get("dag"), "dag_id", None),
        "task_id": getattr(ti, "task_id", None) or getattr(context.get("task"), "task_id", None),
        "run_id": context.get("run_id"),
        "metadata": {"orchestrator": "airflow"},
    }


class OdosSnowflakeOperator(_BaseOperator):
    """Snowflake SQL operator with Odos cost attribution."""

    def execute(self, context: Any) -> Any:
        instrument_all()
        token = OdosContext.set_context(**airflow_context_kwargs(context))
        self.log.info("Odos: cost attribution enabled for %s.%s", self.dag_id, self.task_id)
        try:
            return super().execute(context)
        finally:
            OdosContext.clear(token)
