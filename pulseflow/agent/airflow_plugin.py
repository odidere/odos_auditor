from typing import Any, Dict

from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
from airflow.utils.context import Context

from pulseflow.agent.instrument import PulseFlowContext


class PulseFlowSnowflakeOperator(SnowflakeOperator):
    """
    Drop-in replacement for SnowflakeOperator that enables 
    automated cost attribution and anomaly detection.
    """

    def execute(self, context: Context) -> Any:
        # 1. Capture Identity from Airflow Runtime
        dag_id = context['dag'].dag_id
        task_id = context['task'].task_id
        run_id = context['run_id']

        # 2. Inject Context into the PulseFlow Singleton
        # The existing instrument.py will pick this up during the SQL hook
        PulseFlowContext.set_context(
            dag_id=dag_id,
            task_id=task_id,
            metadata={"run_id": run_id, "orchestrator": "airflow"}
        )

        self.log.info(f"🔮 PulseFlow: Auditing enabled for {dag_id}.{task_id}")

        # 3. Execute the standard Snowflake logic
        # The monkey-patched driver will now tag queries with the IDs above
        try:
            return super().execute(context)
        finally:
            # 4. Cleanup to prevent context bleeding
            PulseFlowContext.clear()
