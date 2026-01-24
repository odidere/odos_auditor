from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator

from odos.agent.instrument import OdosContext


def task_policy(task):
    """
    Automatically inject Odos auditing into any Snowflake task.
    """
    if isinstance(task, SnowflakeOperator):
        # We wrap the pre_execute hook to set context
        original_pre_execute = task.pre_execute

        def odos_wrapper(context):
            OdosContext.set_context(
                dag_id=task.dag_id,
                task_id=task.task_id
            )
            if original_pre_execute:
                original_pre_execute(context)

        task.pre_execute = odos_wrapper
