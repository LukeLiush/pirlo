import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pirlo.core.models.link import LlmLink
from pirlo.core.ports.decomposer import DecomposerPort
from pirlo.core.repository.plan_repository import PlanRepository
from pirlo.core.services import WorkflowRunner
from pirlo.infrastructure.adapters.orchestrator.prefect_lifecycle import (
    pirlo_decomposed_flow,
)

logger = logging.getLogger(__name__)


class DecomposedWorkflowRunner(WorkflowRunner):
    """Orchestrates plan caching, task decomposition, parallel execution, and result aggregation."""

    def __init__(
        self,
        plan_repository: PlanRepository,
        decomposer: DecomposerPort,
        subtask_runner_fn: Callable[..., Awaitable[Any]] | Callable[..., Any],
        aggregator_link: LlmLink | None = None,
        workspace: Path | str | None = None,
        playbook: str | None = None,
    ) -> None:
        self.plan_repository = plan_repository
        self.decomposer = decomposer
        self.subtask_runner_fn = subtask_runner_fn
        self.aggregator_link = aggregator_link
        self.workspace: Path | None = (
            Path(workspace) if isinstance(workspace, str) else workspace
        )
        self.playbook = playbook

    async def run(
        self,
        task_prompt: str,
        cache_key: str | None = None,
        run_id: str | None = None,
    ) -> str:
        # 1. Tier 1 Cache Check: Plan Repository
        plan_id: str = cache_key or task_prompt
        plan = None
        if self.plan_repository.exists(plan_id):
            try:
                logger.info(
                    f"Plan Cache HIT for '{task_prompt}' [plan_id={plan_id}]. Bypassing Decomposer Agent..."
                )
                plan = self.plan_repository.load(plan_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Failed to load cached plan '{plan_id}': {e}. Re-running Decomposer Agent..."
                )

        if not plan:
            logger.info(
                f"Plan Cache MISS for '{task_prompt}' [plan_id={plan_id}]. Executing Decomposer Agent..."
            )
            plan = await self.decomposer.decompose(task_prompt)
            plan.plan_id = plan_id
            self.plan_repository.save(plan)
            logger.info(
                f"Saved new DecomposerPlan '{plan_id}' with {len(plan.subtasks)} subtasks to Plan Cache."
            )

        # 2. Parallel Subtask Execution via Prefect Flow
        from prefect.settings import (
            PREFECT_API_URL,
            PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
            temporary_settings,
        )

        from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
            discover_prefect_server_url,
        )

        active_api_url = discover_prefect_server_url()
        override_settings = (
            {PREFECT_API_URL: active_api_url}
            if active_api_url
            else {PREFECT_API_URL: None, PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True}
        )

        with temporary_settings(override_settings):
            return await pirlo_decomposed_flow(
                plan=plan,
                worker_fn=self.subtask_runner_fn,
                link=self.aggregator_link,
                workspace=self.workspace,
                playbook=self.playbook,
                run_name=cache_key,
                run_id=run_id,
            )
