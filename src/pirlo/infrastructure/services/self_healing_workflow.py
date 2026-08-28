import logging

from playwright.async_api import Page as PlaywrightPage

from pirlo.core.models.execution_context import DEFAULT_CONTEXT, ExecutionContext
from pirlo.core.repository.workflow_repository import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner

logger = logging.getLogger(__name__)


class SelfHealingRunner(WorkflowRunner[PlaywrightPage]):
    """Composite/Orchestrator runner that coordinates cached replay and LLM fallback execution."""

    replay_runner: WorkflowRunner[PlaywrightPage]
    fallback_runner: WorkflowRunner[PlaywrightPage]
    repository: WorkflowRepository
    cdp_url: str

    def __init__(
        self,
        replay_runner: WorkflowRunner[PlaywrightPage],
        fallback_runner: WorkflowRunner[PlaywrightPage],
        repository: WorkflowRepository,
        cdp_url: str = "http://localhost:9222",
    ) -> None:
        self.replay_runner = replay_runner
        self.fallback_runner = fallback_runner
        self.repository = repository
        self.cdp_url = cdp_url

    async def run(
        self,
        task_prompt: str,
        context: ExecutionContext[PlaywrightPage] = DEFAULT_CONTEXT,
    ) -> str:
        page = context.page
        cache_key = context.cache_key

        # 1. Attempt cached deterministic replay if present
        if cache_key and self.repository.exists(cache_key):
            logger.info(
                f"Cached workflow '{cache_key}' found. Initiating deterministic replay..."
            )
            try:
                result: str = await self.replay_runner.run(task_prompt, context=context)
                logger.info("Deterministic replay completed successfully.")
                return result
            except Exception as e:
                logger.warning(
                    f"Replay failed due to safety check violation or page layout mutation ({e}). "
                    "Resetting browser context for fresh fallback...",
                    exc_info=True,
                )
                if page is not None:
                    try:
                        await page.goto("about:blank")
                    except Exception as goto_err:  # noqa: BLE001
                        logger.warning(
                            f"Failed to navigate page to about:blank: {goto_err}"
                        )
                else:
                    await self._reset_browser_session(self.cdp_url)
                logger.info(
                    "Triggering fallback browser-use agent to self-heal workflow cache..."
                )
        else:
            logger.info(
                f"No cached workflow found for '{cache_key}'. Initiating fallback browser-use agent..."
            )

        # 2. Execute fallback runner (runs browser-use agent and updates the repository cache)
        return await self.fallback_runner.run(task_prompt, context=context)

    @staticmethod
    async def _reset_browser_session(cdp_url: str = "http://localhost:9222") -> None:
        """Navigates active CDP browser session to about:blank to ensure fresh start."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.get(f"{cdp_url}/json/new?about:blank", timeout=2.0)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not reset CDP browser tab at {cdp_url}: {e}")
