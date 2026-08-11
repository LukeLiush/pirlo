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

    async def run(
        self,
        task_prompt: str,
        cache_key: str | None = None,
        run_id: str | None = None,
    ) -> str:
        if not cache_key:
            cache_key = generate_deterministic_id(task_prompt)

        # 1. Attempt cached deterministic replay if present
        if self.repository.exists(cache_key):
            logger.info(
                f"Cached workflow '{cache_key}' found. Initiating deterministic replay..."
            )
            try:
                result: str = await self.replay_runner.run(
                    task_prompt=task_prompt, cache_key=cache_key, run_id=run_id
                )
                logger.info("Deterministic replay completed successfully.")
                return result
            except Exception as e:
                logger.warning(
                    f"Replay failed due to safety check violation or page layout mutation ({e}). "
                    "Resetting browser context for fresh fallback...",
                    exc_info=True,
                )
                await self._reset_browser_session()
                logger.info(
                    "Triggering fallback browser-use agent to self-heal workflow cache..."
                )
        else:
            logger.info(
                f"No cached workflow found for '{cache_key}'. Initiating fallback browser-use agent..."
            )

        # 2. Execute fallback runner (runs browser-use agent and updates the repository cache)
        return await self.fallback_runner.run(
            task_prompt=task_prompt, cache_key=cache_key, run_id=run_id
        )

    async def _reset_browser_session(self) -> None:
        """Navigates active CDP browser session to about:blank to ensure fresh start."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.get(
                    "http://localhost:9222/json/new?about:blank", timeout=2.0
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not reset CDP browser tab: {e}")
