# src/pirlo/infrastructure/adapters/orchestrator/prefect_runner.py
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Generator
from typing import Any

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
    PrefectLink,
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
        compiler: PrefectCompiler | None = None,
        link: PrefectLink | None = None,
    ) -> None:
        self.compiler: PrefectCompiler = compiler or PrefectCompiler()
        self.link: PrefectLink = link or PrefectLink()

    def _resolve_active_api_url(self) -> str | None:
        if self.link.is_ephemeral:
            return None
        active_api_url: str | None = self.link.server_url
        if active_api_url is None:
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

        if self.link.is_ephemeral or active_api_url is None:
            override_settings: dict[Any, Any] = {
                PREFECT_API_URL: None,
                PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
            }
        else:
            override_settings = {PREFECT_API_URL: active_api_url}

        override_settings[PREFECT_LOGGING_EXTRA_LOGGERS] = ["pirlo"]
        override_settings[PREFECT_LOGGING_LOG_PRINTS] = True
        return override_settings

    @contextlib.contextmanager
    def _sync_environ(self, settings: dict[Any, Any]) -> Generator[None, None, None]:
        """Syncs Prefect settings to os.environ so spawned child processes inherit them."""
        orig_env = dict(os.environ)
        try:
            from prefect.settings import PREFECT_API_URL

            if settings.get(PREFECT_API_URL):
                os.environ["PREFECT_API_URL"] = str(settings[PREFECT_API_URL])
            yield
        finally:
            os.environ.clear()
            os.environ.update(orig_env)

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
        if not self.link.is_ephemeral and self.link.work_pool:
            return await self._submit_remote_run(
                workflow, force=force, show_logs=show_logs, **kwargs
            )
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
        import hashlib

        from pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint import (
            run_play_remote,
        )
        from pirlo.infrastructure.services.code_bundler import (
            build_worker_bootstrap_command,
            create_tarball_bytes,
            get_code_storage_backend,
        )

        cron_expr = ROUTINE_PRESETS.get(routine.lower(), routine)
        override_settings = self._get_override_settings()

        with (
            temporary_settings(override_settings),
            self._sync_environ(override_settings),
        ):
            storage = get_code_storage_backend(self.link.code_storage)
            tar_bytes = create_tarball_bytes()
            snapshot_hash = hashlib.sha256(tar_bytes).hexdigest()[:12]
            code_ref = await storage.upload(
                tar_bytes, snapshot_name=f"{workflow.name}-{snapshot_hash}"
            )

            deployment_name = f"pirlo-{workflow.name}-{routine}"
            payload: dict[str, Any] = {
                "play_name": workflow.name,
                "parameters": kwargs,
                "code_ref": code_ref,
                "storage_type": self.link.code_storage,
                "force": False,
                "show_logs": False,
            }
            import inspect

            bootstrap_cmd = build_worker_bootstrap_command()
            raw_deployment: Any = run_play_remote.to_deployment(
                name=deployment_name,
                cron=cron_expr,
                work_pool_name=self.link.work_pool or DEFAULT_WORK_POOL,
                parameters=payload,
                job_variables={"command": bootstrap_cmd},
                enforce_parameter_schema=False,
            )
            deployment: Any = (
                await raw_deployment
                if inspect.isawaitable(raw_deployment)
                else raw_deployment
            )
            deployment_id = await deployment.apply()
            dashboard_url = self.get_dashboard_url(str(deployment_id))
            return PrefectRoutineRegistration(
                registration_id=str(deployment_id),
                play_name=workflow.name,
                routine=cron_expr,
                dashboard_url=dashboard_url,
                work_pool=self.link.work_pool or DEFAULT_WORK_POOL,
            )

    async def _submit_remote_run(
        self,
        workflow: PrefectWorkflow,
        *,
        force: bool = False,
        show_logs: bool = False,
        **kwargs: Any,
    ) -> PrefectRoutineRegistration:
        """Submits a flow run to the remote Prefect work pool without running locally."""
        import hashlib

        from prefect.client.orchestration import get_client
        from prefect.deployments import run_deployment

        from pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint import (
            run_play_remote,
        )
        from pirlo.infrastructure.services.code_bundler import (
            build_worker_bootstrap_command,
            create_tarball_bytes,
            get_code_storage_backend,
        )

        override_settings = self._get_override_settings()

        with (
            temporary_settings(override_settings),
            self._sync_environ(override_settings),
        ):
            storage = get_code_storage_backend(self.link.code_storage)
            tar_bytes = create_tarball_bytes()
            snapshot_hash = hashlib.sha256(tar_bytes).hexdigest()[:12]
            code_ref = await storage.upload(
                tar_bytes, snapshot_name=f"{workflow.name}-{snapshot_hash}"
            )

            deployment_name = f"pirlo-{workflow.name}"
            payload: dict[str, Any] = {
                "play_name": workflow.name,
                "parameters": kwargs,
                "code_ref": code_ref,
                "storage_type": self.link.code_storage,
                "force": force,
                "show_logs": show_logs,
            }

            import inspect

            bootstrap_cmd = build_worker_bootstrap_command()
            raw_deployment: Any = run_play_remote.to_deployment(
                name=deployment_name,
                work_pool_name=self.link.work_pool or DEFAULT_WORK_POOL,
                parameters=payload,
                job_variables={"command": bootstrap_cmd},
                enforce_parameter_schema=False,
            )
            deployment: Any = (
                await raw_deployment
                if inspect.isawaitable(raw_deployment)
                else raw_deployment
            )
            await deployment.apply()

            raw_flow_run: Any = run_deployment(
                name=f"pirlo_remote_runner/{deployment_name}",
                parameters=payload,
                timeout=None if show_logs else 0,
            )
            flow_run: Any = (
                await raw_flow_run
                if inspect.isawaitable(raw_flow_run)
                else raw_flow_run
            )

            run_identifier = getattr(flow_run, "name", None) or str(flow_run.id)
            dashboard_url = self.get_dashboard_url(run_identifier)

            if show_logs:
                from prefect.client.schemas.filters import (
                    LogFilter,
                    LogFilterFlowRunId,
                )

                async with get_client() as client:
                    offset = 0
                    while True:
                        logs = await client.read_logs(
                            log_filter=LogFilter(
                                flow_run_id=LogFilterFlowRunId(any_=[flow_run.id])
                            ),
                            offset=offset,
                        )
                        for log_entry in logs:
                            logger.info(log_entry.message)
                        offset += len(logs)

                        refreshed = await client.read_flow_run(flow_run.id)
                        if refreshed.state and refreshed.state.is_final():
                            break
                        await asyncio.sleep(1.5)

            return PrefectRoutineRegistration(
                registration_id=str(flow_run.id),
                play_name=workflow.name,
                routine=None,
                dashboard_url=dashboard_url,
                work_pool=self.link.work_pool or DEFAULT_WORK_POOL,
            )

    async def _run_immediate_once(
        self,
        workflow: PrefectWorkflow,
        *,
        force: bool = False,
        show_logs: bool = False,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Executes the workflow immediately once.

        When called from within a running event loop (e.g., pytest-anyio),
        Prefect's ephemeral server startup interferes with the caller's loop.
        In that case we run the flow in a dedicated OS thread with its own
        ``asyncio.run()`` so Prefect gets a completely isolated event loop.
        """
        override_settings = self._get_override_settings()

        async def _run_flow_isolated() -> PlayOutput | None:
            with (
                temporary_settings(override_settings),
                self._sync_environ(override_settings),
            ):
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

        import concurrent.futures

        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We are inside a running event loop (e.g., pytest-anyio).
            # Run the flow in an isolated thread so Prefect can use asyncio.run()
            # without conflicting with the caller's loop.
            def _run_in_thread() -> PlayOutput | None:
                return asyncio.run(_run_flow_isolated())

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future: concurrent.futures.Future[PlayOutput | None] = pool.submit(
                    _run_in_thread
                )
                # Await the thread-pool future without blocking the caller's loop.
                return await asyncio.wrap_future(future)

        # No running loop — run directly (normal CLI path).
        return await _run_flow_isolated()

    def get_dashboard_url(self, run_id: str) -> str | None:
        """Constructs Prefect dashboard URL if pirlo connect or a remote Prefect server is active."""
        if self.link.is_ephemeral:
            return None
        active_api_url: str | None = self._resolve_active_api_url()
        if not active_api_url:
            return None

        web_url = active_api_url.removesuffix("/api").rstrip("/")
        return f"{web_url}/flow-runs?name={run_id}"
