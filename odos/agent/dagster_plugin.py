from dagster import ConfigurableResource, InitResourceContext

from .instrument import OdosContext, instrument_all


class OdosResource(ConfigurableResource):
    """Dagster 1.12+ compatible resource for automated tracing."""

    def setup_for_execution(self, context: InitResourceContext) -> None:
        instrument_all()
        OdosContext.set_context(
            dag_id=context.dagster_run.job_name if context.dagster_run else "ad-hoc",
            task_id=context.op_handle.name if context.op_handle else "asset",
            run_id=context.run_id
        )
