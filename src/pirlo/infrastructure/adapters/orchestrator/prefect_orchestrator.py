from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

logger = logging.getLogger(__name__)

from prefect.settings import temporary_settings

from pirlo.core.config import get_workspace_path
from pirlo.core.decorators import orchestrator
from pirlo.core.models.execution_context import ExecutionContext
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import PreparedRun
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.core.services.schedule_resolver import (
    PRESET_SCHEDULES,
    detect_local_timezone,
    get_schedule_help_text,
)
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


def _get_server_url_help() -> str:
    from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
        discover_prefect_server_url,
    )

    detected = discover_prefect_server_url()
    if detected:
        return f"Prefect Server API endpoint URL [detected server: {detected} 🌐]"
    return "Prefect Server API endpoint URL [default: Ephemeral Mode (In-Process) ⚡]"


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
            str | None,
            Parameter(
                help=get_schedule_help_text(),
                short="-s",
            ),
        ] = None,
        server_url: Annotated[
            str | None,
            Parameter(
                help=_get_server_url_help(),
                env_name="SERVER_URL",
            ),
        ] = None,
        work_pool: Annotated[
            str | None,
            Parameter(
                help="Prefect work pool name (required when --schedule is used)",
                env_name="WORK_POOL",
            ),
        ] = None,
        decomposer_link: Annotated[
            LlmLink | str | None,
            LinkParameter(
                help="LLM link name for task decomposition [default: auto-detected from playbook parameters]",
                env_name="DECOMPOSER_LINK",
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
        decomposer_link = self._get_decomposer_link(prepared_run)
        aggregator_link = self._get_aggregator_link(prepared_run)
        return DecomposedWorkflowRunner(
            plan_repository=JsonFilePlanRepository(workspace / "plans"),
            decomposer=self._build_decomposer(decomposer_link),
            subtask_runner_fn=worker_fn,
            aggregator_link=aggregator_link,
            workspace=workspace,
            playbook=prepared_run.playbook_name,
        )

    def _build_decomposer(self, link: LlmLink) -> PydanticAiDecomposer:
        return PydanticAiDecomposer(link=link)

    def _get_decomposer_link(self, prepared_run: PreparedRun | None = None) -> LlmLink:
        from pirlo.infrastructure.adapters.storage.composite_link_repository import (
            CompositeLinkRepository,
        )

        repo = CompositeLinkRepository()

        # 1. Explicit orchestrator override: --decomposer-link
        if self.decomposer_link:
            if isinstance(self.decomposer_link, LlmLink):
                return self.decomposer_link

            link_name = str(self.decomposer_link)
            link = repo.get_by_name(link_name)
            if link:
                return link
            raise ValueError(
                f"Specified decomposer link '{link_name}' not found in link repository."
            )

        # 2. Dynamic scanning: Pick the first LlmLink present in prepared_run parameters
        if prepared_run and prepared_run.parameters:
            for param_name, param_val in prepared_run.parameters.items():
                if isinstance(param_val, LlmLink):
                    logger.info(
                        "🧩 Decomposer automatically using '%s' link '%s' (Provider: %s, Model: %s) for task breakdown.",
                        param_name,
                        param_val.name,
                        param_val.provider,
                        param_val.model,
                    )
                    return param_val

        # 3. If no LlmLink is found in playbook params, --decomposer-link is required
        raise ValueError(
            "No active LLM link found in playbook parameters and no --decomposer-link was specified. "
            "Please specify --decomposer-link <link_name> or pass a valid LlmLink parameter in your playbook."
        )

    def _get_aggregator_link(self, prepared_run: PreparedRun | None = None) -> LlmLink:
        from pirlo.infrastructure.adapters.storage.composite_link_repository import (
            CompositeLinkRepository,
        )

        repo = CompositeLinkRepository()

        # 1. Query default link via is_default indicator (e.g. serve-ollama)
        default_link = repo.get_default_link()
        if default_link:
            logger.info(
                "⚙️ Synthesis aggregator using default local link '%s' (Provider: %s, Model: %s).",
                default_link.name,
                default_link.provider,
                default_link.model,
            )
            return default_link

        # 2. Fallback to decomposer link if no default local link is active
        decomposer_link = self._get_decomposer_link(prepared_run)
        logger.info(
            "🔍 No active default local link found (e.g., 'serve-ollama'). "
            "Falling back to decomposer link '%s' (Provider: %s, Model: %s) for synthesis.",
            decomposer_link.name,
            decomposer_link.provider,
            decomposer_link.model,
        )
        return decomposer_link

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

        schedule_lower: str = cron_schedule.lower()
        resolved_cron: str = PRESET_SCHEDULES.get(schedule_lower, cron_schedule)
        tz_name: str = detect_local_timezone()

        if schedule_lower in PRESET_SCHEDULES:
            print(
                f"🚀 Pitch set to play {schedule_lower}! ⏰ "
                f"(cron: '{resolved_cron}', timezone: {tz_name})"
            )
        else:
            print(
                f"🚀 Pitch scheduled to play on timer! ⏰ "
                f"(cron: '{resolved_cron}', timezone: {tz_name})"
            )

        print(f"🌐 Prefect Server Detected: {settings.web_ui_base}")

        schedule = CronSchedule(cron=resolved_cron, timezone=tz_name)
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
