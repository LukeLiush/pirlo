# pirlo/infrastructure/adapters/orchestrator/prefect_orchestrator.py
from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prefect.settings import temporary_settings

from pirlo.core.config import get_workspace_path
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
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)
from pirlo.infrastructure.repository.json_file_plan_repository import (
    JsonFilePlanRepository,
)
from pirlo.infrastructure.services.decomposed_workflow import DecomposedWorkflowRunner
from pirlo.infrastructure.services.log_streamer import capture_run_logs
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory


class SmartPrefectTaskOrchestrator(TaskOrchestrator):
    name: str = "prefect"

    server_url = Parameter(
        str,
        default=None,
        help="Prefect Server API endpoint URL (e.g. http://localhost:4200/api)",
        env_name="SERVER_URL",
    )
    work_pool = Parameter(
        str,
        default=None,
        help="Prefect work pool name for scheduled deployments",
        env_name="WORK_POOL",
    )
    decomposer_model = Parameter(
        str,
        default=None,
        help="Model name used by the task decomposer",
        env_name="DECOMPOSER_MODEL",
    )
    decomposer_link = LinkParameter(
        help="LLM link name used to synthesize subtask results",
        env_name="DECOMPOSER_LINK",
    )

    # ---- public API -----------------------------------------------------

    async def execute(
        self,
        task: str,
        prepared_run: PreparedRun,
        worker_fn: Any,
        schedule: str | None = None,
    ) -> Any:
        settings = PrefectServerSettings.resolve(self.server_url)

        with capture_run_logs(
            prepared_run.run_dir, get_prefix_fn=self._prefix_fn(prepared_run)
        ):
            if schedule:
                result = await self._deploy_scheduled(
                    task, prepared_run, schedule, settings
                )
            else:
                result = await self._run_pipeline(
                    task, prepared_run, worker_fn, settings
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
        worker_fn: Any,
        settings: PrefectServerSettings,
    ) -> Any:
        if settings.is_server_mode:
            print(f"🌐 Prefect Server Detected: {settings.web_ui_base}")
        else:
            print("⚡ Running in Prefect Ephemeral Mode (In-Process)")

        runner = self._build_runner(worker_fn, prepared_run)

        with temporary_settings(settings.overrides):
            return await runner.run(
                task_prompt=task,
                cache_key=prepared_run.run_name,
                run_id=prepared_run.run_id,
            )

    def _build_runner(
        self, worker_fn: Any, prepared_run: PreparedRun
    ) -> DecomposedWorkflowRunner:
        workspace = get_workspace_path()
        return DecomposedWorkflowRunner(
            plan_repository=JsonFilePlanRepository(workspace / "plans"),
            decomposer=self._build_decomposer(),
            subtask_runner_fn=worker_fn,
            aggregator_llm=self._build_aggregator_llm(),
            workspace=workspace,
            playbook=prepared_run.playbook_name,
        )

    def _get_resolved_link(self) -> LlmLink:
        if self.decomposer_link:
            if isinstance(self.decomposer_link, LlmLink):
                return self.decomposer_link

            repo = JsonLinkRepository(Path("~/.pirlo-pitch/links.json").expanduser())
            link_name = getattr(
                self.decomposer_link, "_name", str(self.decomposer_link)
            )
            link = repo.get_by_name(link_name)
            if link:
                return link

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
                model=self.decomposer_model or "google-gla:gemini-1.5-flash",
                api_key=api_key,
            )

        # Fallback to local Ollama auto-discovery provider
        from pirlo.infrastructure.services.ollama_resolver import (
            LocalDecomposerModelProvider,
        )

        provider = LocalDecomposerModelProvider()
        return provider.provide_link()

    def _build_decomposer(self) -> PydanticAiDecomposer:
        link = self._get_resolved_link()
        return PydanticAiDecomposer(
            model_name=link.model,
            api_key=link.api_key,
            base_url=link.base_url,
        )

    def _build_aggregator_llm(self) -> Any:
        link = self._get_resolved_link()
        return LlmFactory.create_langchain_llm(
            link=link, temperature=0.0, timeout=120.0
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

    # ---- CLI epilog (moved from TerminalPitch, per earlier discussion) --
    # If you centralize the epilog on OrchestratorFactory instead, delete this.
