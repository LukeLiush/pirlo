# src/pirlo/infrastructure/adapters/orchestrator/prefect_runner.py
from __future__ import annotations

import contextlib
import logging
from typing import Any, Literal

from prefect.settings import (
    PREFECT_API_URL,
    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
    temporary_settings,
)

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.models.orchestrator import ROUTINE_PRESETS, RoutineRegistration
from pirlo.core.ports.runner import PlayRunner
from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
    PrefectRoutineRegistration,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_model import (
    PrefectWorkflow,
)

logger = logging.getLogger(__name__)


class PrefectRunner(PlayRunner):
    """Executes a PrefectWorkflow in ephemeral or connected server mode."""

    def __init__(
        self,
        compiler: PrefectCompiler,
        mode: Literal["auto", "ephemeral", "server"] = "auto",
        server_url: str | None = None,
        work_pool: str = DEFAULT_WORK_POOL,
    ) -> None:
        self.compiler: PrefectCompiler = compiler
        self.mode: Literal["auto", "ephemeral", "server"] = mode
        self.server_url: str | None = server_url
        self.work_pool: str = work_pool

    def _resolve_active_api_url(self) -> str | None:
        active_api_url: str | None = self.server_url
        if active_api_url is None and self.mode in ("auto", "server"):
            active_api_url = discover_prefect_server_url()
        if active_api_url and active_api_url != "ephemeral":
            active_api_url = active_api_url.rstrip("/")
            if not active_api_url.endswith("/api"):
                active_api_url = f"{active_api_url}/api"
        return active_api_url

    def _get_override_settings(self) -> dict[Any, Any]:
        active_api_url = self._resolve_active_api_url()
        from prefect.settings import (
            PREFECT_LOGGING_EXTRA_LOGGERS,
            PREFECT_LOGGING_LOG_PRINTS,
        )

        if self.mode == "ephemeral" or (self.mode == "auto" and active_api_url is None):
            override_settings: dict[Any, Any] = {
                PREFECT_API_URL: None,
                PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
            }
        else:
            override_settings = {PREFECT_API_URL: active_api_url}

        override_settings[PREFECT_LOGGING_EXTRA_LOGGERS] = ["pirlo"]
        override_settings[PREFECT_LOGGING_LOG_PRINTS] = True
        return override_settings

    async def run(
        self,
        blueprint: PlayBlueprint,
        *,
        routine: str | None = None,
        force: bool = False,
        show_logs: bool = False,
        **kwargs: Any,
    ) -> PlayOutput | RoutineRegistration | None:
        """Executes the workflow immediately or registers a recurring routine."""
        workflow: PrefectWorkflow = self.compiler.compile(blueprint)

        if routine:
            return await self._deploy_routine(workflow, routine, **kwargs)
        return await self._run_immediate_once(
            workflow, force=force, show_logs=show_logs, **kwargs
        )

    async def _deploy_routine(
        self,
        workflow: PrefectWorkflow,
        routine: str,
        **kwargs: Any,
    ) -> PrefectRoutineRegistration:
        """Registers a Prefect deployment for a scheduled routine."""
        from prefect.client.schemas.schedules import CronSchedule

        cron_expr = ROUTINE_PRESETS.get(routine.lower(), routine)
        override_settings = self._get_override_settings()

        with temporary_settings(override_settings):
            cron_schedule = CronSchedule(cron=cron_expr)
            flow_callable: Any = workflow.flow
            deployment = await flow_callable.to_deployment(
                name=f"pirlo-routine-{workflow.name}",
                schedule=cron_schedule,
                work_pool_name=self.work_pool or DEFAULT_WORK_POOL,
                parameters=kwargs,
            )
            deployment_id = await deployment.apply()
            dashboard_url = self.get_dashboard_url(str(deployment_id))
            return PrefectRoutineRegistration(
                registration_id=str(deployment_id),
                play_name=workflow.name,
                routine=cron_expr,
                dashboard_url=dashboard_url,
                work_pool=self.work_pool or DEFAULT_WORK_POOL,
            )

    async def _run_immediate_once(
        self,
        workflow: PrefectWorkflow,
        *,
        force: bool = False,
        show_logs: bool = False,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Executes the workflow immediately once."""
        override_settings = self._get_override_settings()

        with temporary_settings(override_settings):
            try:
                res: PlayOutput | None = await workflow(
                    force=force, show_logs=show_logs, **kwargs
                )
                return res
            finally:
                with contextlib.suppress(Exception):
                    import inspect

                    from prefect.logging.handlers import APILogWorker

                    drain_res: Any = APILogWorker.drain_all(at_exit=False)
                    if inspect.isawaitable(drain_res):
                        await drain_res

    def get_dashboard_url(self, run_id: str) -> str | None:
        """Constructs Prefect dashboard URL if pirlo connect or a remote Prefect server is active."""
        active_api_url: str | None = self.server_url
        if active_api_url is None and self.mode in ("auto", "server"):
            active_api_url = discover_prefect_server_url()

        if not active_api_url:
            return None

        web_url = active_api_url.removesuffix("/api").rstrip("/")
        return f"{web_url}/flow-runs?name={run_id}"
