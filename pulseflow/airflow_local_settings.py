from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator

from pulseflow.agent.instrument import PulseFlowContext


def task_policy(task):
    """
    Automatically inject PulseFlow auditing into any Snowflake task.
    """
    if isinstance(task, SnowflakeOperator):
        # We wrap the pre_execute hook to set context
        original_pre_execute = task.pre_execute

        def pulseflow_wrapper(context):
            PulseFlowContext.set_context(
                dag_id=task.dag_id,
                task_id=task.task_id
            )
            if original_pre_execute:
                original_pre_execute(context)

        task.pre_execute = pulseflow_wrapper
