from __future__ import annotations

import contextlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from prefect.settings import temporary_settings

from pirlo.core.config import get_workspace_path
from pirlo.core.decorators import orchestrator
from pirlo.core.models.execution_context import ExecutionContext
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import PreparedRun
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.decomposer.pydantic_ai_decomposer import (
    PydanticAiDecomposer,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_lifecycle import (
    pirlo_decomposed_flow,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
    PrefectServerSettings,
)
from pirlo.infrastructure.repository.json_file_plan_repository import (
    JsonFilePlanRepository,
)
from pirlo.infrastructure.services.decomposed_workflow import (
    DecomposedWorkflowRunner,
    WorkflowRunner,
)
from pirlo.infrastructure.services.log_streamer import capture_run_logs


@orchestrator(
    name="prefect", description="Prefect 3.0 workflow orchestrator engine backend"
)
class SmartPrefectTaskOrchestrator(TaskOrchestrator):
    def __init__(
        self,
        server_url: str | None = None,
        work_pool: str | None = None,
        decomposer_link: LlmLink | str | None = None,
    ) -> None:
        self.server_url = server_url
        self.work_pool = work_pool
        self.decomposer_link = decomposer_link

    # ---- public API -----------------------------------------------------

    async def execute(
        self,
        prepared_run: PreparedRun,
        worker_fn: Callable[..., Awaitable[Any]] | Callable[..., Any],
        task: Annotated[str, Parameter(help="Task prompt to execute")] = "",
        schedule: Annotated[
            str | None, Parameter(help="Schedule preset or cron string", short="-s")
        ] = None,
        server_url: Annotated[
            str | None,
            Parameter(help="Prefect Server API endpoint URL", env_name="SERVER_URL"),
        ] = None,
        work_pool: Annotated[
            str | None, Parameter(help="Prefect work pool name", env_name="WORK_POOL")
        ] = None,
        decomposer_link: Annotated[
            LlmLink | str | None,
            LinkParameter(
                help="LLM link name for decomposer", env_name="DECOMPOSER_LINK"
            ),
        ] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # Override instance attrs if passed explicitly in execute kwargs
        if server_url is not None:
            self.server_url = server_url
        if work_pool is not None:
            self.work_pool = work_pool
        if decomposer_link is not None:
            self.decomposer_link = decomposer_link

        task_str: str = task or str(prepared_run.parameters.get("task", ""))
        schedule_str: str | None = schedule or prepared_run.parameters.get("schedule")

        # Auto-detect active pirlo connect session for server_url if not explicitly provided
        if not self.server_url:
            from pirlo.core.models.serve_manifest import ActiveSession

            connect_session = ActiveSession.load_active(
                get_workspace_path() / "connect" / "session.json"
            )
            if connect_session:
                self.server_url = connect_session.prefect_api_url

        settings: PrefectServerSettings = PrefectServerSettings.resolve(self.server_url)

        with capture_run_logs(
            prepared_run.run_dir, get_prefix_fn=self._prefix_fn(prepared_run)
        ):
            if schedule_str:
                result = await self._deploy_scheduled(
                    task_str, prepared_run, schedule_str, settings
                )
            else:
                result = await self._run_pipeline(
                    task_str, prepared_run, worker_fn, settings
                )

        print(
            f"\n💡 To view detailed inspection & execution history, run:\n"
            f"   pirlo run show {prepared_run.run_id}"
        )
        return result

    # ---- pipeline (immediate) execution --------------------------------

    async def _run_pipeline(
        self,
        task: str,
        prepared_run: PreparedRun,
        worker_fn: Callable[..., Awaitable[Any]] | Callable[..., Any],
        settings: PrefectServerSettings,
    ) -> str:
        if settings.is_server_mode:
            print(f"🌐 Prefect Server Detected: {settings.web_ui_base}")
        else:
            print("⚡ Running in Prefect Ephemeral Mode (In-Process)")

        workflow_runner: WorkflowRunner = self._build_runner(worker_fn, prepared_run)

        with temporary_settings(settings.overrides):
            res: str = await workflow_runner.run(
                task_prompt=task,
                context=ExecutionContext(
                    cache_key=prepared_run.run_name,
                    run_id=prepared_run.run_id,
                ),
            )
            return res

    def _build_runner(
        self,
        worker_fn: Callable[..., Awaitable[Any]] | Callable[..., Any],
        prepared_run: PreparedRun,
    ) -> WorkflowRunner:
        workspace: Path = get_workspace_path()
        return DecomposedWorkflowRunner(
            plan_repository=JsonFilePlanRepository(workspace / "plans"),
            decomposer=self._build_decomposer(),
            subtask_runner_fn=worker_fn,
            aggregator_link=self._get_resolved_link(),
            workspace=workspace,
            playbook=prepared_run.playbook_name,
        )

    def _get_resolved_link(self) -> LlmLink:
        from pirlo.infrastructure.adapters.storage.composite_link_repository import (
            CompositeLinkRepository,
        )

        if self.decomposer_link:
            if isinstance(self.decomposer_link, LlmLink):
                return self.decomposer_link

            repo = CompositeLinkRepository()
            link_name = getattr(
                self.decomposer_link, "_name", str(self.decomposer_link)
            )
            link = repo.get_by_name(link_name)
            if link:
                return link

        # Fall back to serve-ollama from composite repo if active connect session exists
        repo = CompositeLinkRepository()
        serve_link = repo.get_by_name("serve-ollama")
        if serve_link:
            return serve_link

        # Check if environment variable API keys exist for cloud providers
        api_key = (
            os.environ.get("PIRLO_DECOMPOSER_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if api_key:
            return LlmLink(
                name="cloud-env-link",
                provider="gemini",
                model="google-gla:gemini-1.5-flash",
                api_key=api_key,
            )

        # Fallback default link if no link or env key provided
        return LlmLink(
            name="default-gemini",
            provider="gemini",
            model="google-gla:gemini-1.5-flash",
            api_key="",
        )

    def _build_decomposer(self) -> PydanticAiDecomposer:
        link = self._get_resolved_link()
        return PydanticAiDecomposer(
            model_name=link.model,
            api_key=link.api_key,
            base_url=link.base_url,
        )

    # ---- scheduled deployment ------------------------------------------

    async def _deploy_scheduled(
        self,
        task: str,
        prepared_run: PreparedRun,
        cron_schedule: str,
        settings: PrefectServerSettings,
    ) -> Any:
        if not settings.is_server_mode:
            raise RuntimeError(
                "⚠️ Prefect Server is required for --schedule. "
                "Start a local server with 'prefect server start' or configure PREFECT_API_URL."
            )

        from prefect.client.schemas.schedules import CronSchedule

        print(f"⏰ Scheduling Prefect Flow with cron: '{cron_schedule}'")
        print(f"🌐 Prefect Server Detected: {settings.web_ui_base}")

        schedule = CronSchedule(cron=cron_schedule, timezone="UTC")
        deployment = await pirlo_decomposed_flow.to_deployment(  # type: ignore[misc]
            name=f"pirlo-scheduled-{prepared_run.run_id}",
            schedule=schedule,  # type: ignore[arg-type]
            work_pool_name=self.work_pool,
        )
        print(
            f"✅ Created scheduled Prefect deployment: pirlo-scheduled-{prepared_run.run_id}"
        )
        return deployment

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _prefix_fn(prepared_run: PreparedRun) -> Callable[[], str]:
        def get_active_task_prefix() -> str:
            with contextlib.suppress(Exception):
                from prefect.context import (
                    FlowRunContext,
                    TaskRunContext,
                    get_run_context,
                )

                ctx = get_run_context()
                if isinstance(ctx, TaskRunContext) and ctx.task_run:
                    name = ctx.task_run.name or ctx.task_run.task_key
                    return f"[{name}]"
                if isinstance(ctx, FlowRunContext) and ctx.flow_run:
                    return f"[{ctx.flow_run.name}]"
            return f"[{prepared_run.run_name.capitalize()} Flow]"

        return get_active_task_prefix
