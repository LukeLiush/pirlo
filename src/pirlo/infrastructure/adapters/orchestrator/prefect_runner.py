# src/pirlo/infrastructure/adapters/orchestrator/prefect_runner.py
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import httpx
from prefect.settings import temporary_settings

from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.models.orchestrator import ROUTINE_PRESETS, RoutineRegistration
from pirlo.core.ports.runner import PlayRunner
from pirlo.core.services.masking import mask_sensitive_data
from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
    PrefectRoutineRegistration,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_model import (
    PrefectWorkflow,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
    Execution,
    PrefectTarget,
)

logger = logging.getLogger(__name__)


class PrefectRunner(PlayRunner):
    """Executes a PrefectWorkflow wherever its PrefectTarget says: ephemeral, in-process or a work pool."""

    def __init__(
        self,
        compiler: PrefectCompiler | None = None,
        target: PrefectTarget | None = None,
    ) -> None:
        self.compiler: PrefectCompiler = compiler or PrefectCompiler()
        self.target: PrefectTarget = target or PrefectTarget.ephemeral()

    def _get_override_settings(self) -> dict[Any, Any]:
        from prefect.settings import (
            PREFECT_LOGGING_EXTRA_LOGGERS,
            PREFECT_LOGGING_LOG_PRINTS,
        )

        return {
            **self.target.server.overrides,
            PREFECT_LOGGING_EXTRA_LOGGERS: ["pirlo"],
            PREFECT_LOGGING_LOG_PRINTS: True,
        }

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
        match self.target.execution:
            case Execution.WORK_POOL:
                return await self._submit_remote_run(
                    workflow, force=force, show_logs=show_logs, **kwargs
                )
            case Execution.IN_PROCESS | Execution.EPHEMERAL:
                return await self._run_immediate_once(
                    workflow, force=force, show_logs=show_logs, **kwargs
                )

    async def _register_deployment(
        self,
        workflow: PrefectWorkflow,
        name: str,
        *,
        parameters: dict[str, Any],
        cron: str | None = None,
        force: bool = False,
        show_logs: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
        """Uploads a code snapshot, then creates and applies its deployment.

        Returns (deployment_id, payload). Call inside the runner's
        temporary_settings / _sync_environ context.
        """
        import hashlib
        import inspect

        from pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint import (
            run_play_remote,
        )
        from pirlo.infrastructure.services.code_bundler import (
            build_worker_bootstrap_command,
            create_tarball_bytes,
            get_code_storage_backend,
        )

        storage = get_code_storage_backend(self.target.code_storage)
        tar_bytes = create_tarball_bytes()
        snapshot_hash = hashlib.sha256(tar_bytes).hexdigest()[:12]
        code_ref = await storage.upload(
            tar_bytes, snapshot_name=f"{workflow.name}-{snapshot_hash}"
        )

        payload: dict[str, Any] = {
            "play_name": workflow.name,
            "parameters": parameters,
            "code_ref": code_ref,
            "storage_type": self.target.code_storage,
            "force": force,
            "show_logs": show_logs,
        }
        # One-off runs must not carry a schedule, or every submission would recur.
        schedule: dict[str, Any] = {"cron": cron} if cron else {}
        raw_deployment: Any = run_play_remote.to_deployment(
            name=name,
            work_pool_name=self.target.work_pool,
            parameters=payload,
            job_variables={"command": build_worker_bootstrap_command()},
            enforce_parameter_schema=False,
            **schedule,
        )
        deployment: Any = (
            await raw_deployment
            if inspect.isawaitable(raw_deployment)
            else raw_deployment
        )
        return await deployment.apply(), payload

    async def _deploy_routine(
        self,
        workflow: PrefectWorkflow,
        routine: str,
        **kwargs: Any,
    ) -> PrefectRoutineRegistration:
        """Registers a Prefect deployment for a scheduled routine."""
        cron_expr = ROUTINE_PRESETS.get(routine.lower(), routine)
        override_settings = self._get_override_settings()

        with (
            temporary_settings(override_settings),
            self._sync_environ(override_settings),
        ):
            deployment_id, _ = await self._register_deployment(
                workflow,
                f"pirlo-{workflow.name}-{routine}",
                parameters=kwargs,
                cron=cron_expr,
            )
            dashboard_url = self.get_deployment_url(str(deployment_id))
            return PrefectRoutineRegistration(
                registration_id=str(deployment_id),
                play_name=workflow.name,
                routine=cron_expr,
                dashboard_url=dashboard_url,
                work_pool=self.target.work_pool,
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
        import inspect

        from prefect.client.orchestration import get_client
        from prefect.deployments import run_deployment

        override_settings = self._get_override_settings()

        with (
            temporary_settings(override_settings),
            self._sync_environ(override_settings),
        ):
            deployment_name = f"pirlo-{workflow.name}"
            _, payload = await self._register_deployment(
                workflow,
                deployment_name,
                parameters=kwargs,
                force=force,
                show_logs=show_logs,
            )

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

            dashboard_url = self._flow_run_url(str(flow_run.id))

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
                work_pool=self.target.work_pool,
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
                    # Flow arguments only feed run history; plays read their inputs
                    # from the blueprint, so secrets never need to be stored here
                    res: PlayOutput | None = await workflow(
                        force=force,
                        show_logs=show_logs,
                        **mask_sensitive_data(
                            kwargs, sensitive_keys=set(workflow.sensitive_parameters)
                        ),
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
        """Links to the flow run named run_id on the target server, or None when ephemeral.

        Falls back to a Runs search for run_id when the run can't be looked up.
        """
        web_ui_base = self.target.server.web_ui_base
        if not web_ui_base:
            return None
        flow_run_id = self._find_flow_run_id(run_id)
        if flow_run_id:
            return self._flow_run_url(flow_run_id)
        return f"{web_ui_base}/runs?flow-run-search={quote(run_id)}"

    def get_deployment_url(self, deployment_id: str) -> str | None:
        """Links to a deployment's page on the target server, or None when ephemeral."""
        web_ui_base = self.target.server.web_ui_base
        if not web_ui_base:
            return None
        return f"{web_ui_base}/deployments/deployment/{deployment_id}"

    def _flow_run_url(self, flow_run_id: str) -> str | None:
        web_ui_base = self.target.server.web_ui_base
        return f"{web_ui_base}/runs/flow-run/{flow_run_id}" if web_ui_base else None

    def _find_flow_run_id(self, run_name: str) -> str | None:
        """Looks up a flow run's id by its name; one quick call, no retries."""
        from prefect.client.orchestration import get_client
        from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterName
        from prefect.settings import PREFECT_CLIENT_MAX_RETRIES

        name_filter = FlowRunFilter(name=FlowRunFilterName(any_=[run_name]))
        with temporary_settings(
            {**self.target.server.overrides, PREFECT_CLIENT_MAX_RETRIES: 0}
        ):
            try:
                with get_client(
                    sync_client=True, httpx_settings={"timeout": 2.0}
                ) as client:
                    runs = client.read_flow_runs(flow_run_filter=name_filter, limit=1)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Couldn't look up flow run %s on %s (%s); linking to a search instead.",
                    run_name,
                    self.target.server.api_url,
                    exc,
                )
                return None
        return str(runs[0].id) if runs else None
