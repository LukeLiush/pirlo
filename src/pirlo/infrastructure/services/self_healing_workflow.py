import logging

from pirlo.core.repository.workflow import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.services.workflow_service import generate_deterministic_id

logger = logging.getLogger(__name__)


class SelfHealingRunner(WorkflowRunner):
    """Composite/Orchestrator runner that coordinates cached replay and LLM fallback execution."""

    replay_runner: WorkflowRunner
    fallback_runner: WorkflowRunner
    repository: WorkflowRepository

    def __init__(
        self,
        replay_runner: WorkflowRunner,
        fallback_runner: WorkflowRunner,
        repository: WorkflowRepository,
    ) -> None:
        self.replay_runner = replay_runner
        self.fallback_runner = fallback_runner
        self.repository = repository

    async def run(self, task_prompt: str, workflow_id: str | None = None) -> str:
        if not workflow_id:
            workflow_id = generate_deterministic_id(task_prompt)

        # 1. Attempt cached deterministic replay if present
        if self.repository.exists(workflow_id):
            logger.info(
                f"Cached workflow '{workflow_id}' found. Initiating deterministic replay..."
            )
            try:
                result: str = await self.replay_runner.run(
                    task_prompt=task_prompt, workflow_id=workflow_id
                )
                logger.info("Deterministic replay completed successfully.")
                return result
            except Exception:
                logger.warning(
                    "Replay failed due to safety check violation or page layout mutation:",
                    exc_info=True,
                )
                logger.info(
                    "Triggering fallback browser-use agent to self-heal workflow cache..."
                )
        else:
            logger.info(
                f"No cached workflow found for '{workflow_id}'. Initiating fallback browser-use agent..."
            )

        # 2. Execute fallback runner (runs browser-use agent and updates the repository cache)
        return await self.fallback_runner.run(
            task_prompt=task_prompt, workflow_id=workflow_id
        )
