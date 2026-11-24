"""Optional Airflow cluster policy: tag queries from *every* task, no DAG changes.

Copy (or import) this ``task_policy`` into your ``airflow_local_settings.py``.
The context is set in ``pre_execute`` and cleared in ``post_execute``.
"""
from __future__ import annotations

from odos.agent.airflow_plugin import airflow_context_kwargs
from odos.agent.context import OdosContext
from odos.agent.instrument import instrument_all


def task_policy(task) -> None:
    original_pre = task.pre_execute
    original_post = task.post_execute

    def odos_pre_execute(context, *args, **kwargs):
        instrument_all()
        OdosContext.set_context(**airflow_context_kwargs(context))
        return original_pre(context, *args, **kwargs)

    def odos_post_execute(context, *args, **kwargs):
        try:
            return original_post(context, *args, **kwargs)
        finally:
            OdosContext.clear()

    task.pre_execute = odos_pre_execute
    task.post_execute = odos_post_execute
