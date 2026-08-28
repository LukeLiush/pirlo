import logging

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightContext
from playwright.async_api import Page as PlaywrightPage
from playwright.async_api import async_playwright

from pirlo.core.models.actions import Action, DoneAction
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.link import LlmLink
from pirlo.core.models.workflow import Workflow
from pirlo.core.repository.run_history_repository import RunHistoryRepository
from pirlo.core.repository.workflow_repository import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.adapters.browser.playwright_adapter import PlaywrightAdapter

logger = logging.getLogger(__name__)


class PlaywrightReplayRunner(WorkflowRunner):
    """Executes a cached domain Workflow sequence deterministically using standard Playwright."""

    repository: WorkflowRepository
    link: LlmLink | None
    browser_config: BrowserConfig
    run_history_repository: RunHistoryRepository | None

    def __init__(
        self,
        repository: WorkflowRepository,
        link: LlmLink | None = None,
        browser_config: BrowserConfig | None = None,
        run_history_repository: RunHistoryRepository | None = None,
    ) -> None:
        self.repository = repository
        self.link = link
        self.browser_config = browser_config or BrowserConfig()
        self.run_history_repository = run_history_repository

    async def run(
        self,
        task_prompt: str,
        cache_key: str | None = None,
        run_id: str | None = None,
    ) -> str:
        workflow_id = cache_key

        # Load from repository boundary
        if not workflow_id:
            raise ValueError("cache_key (workflow_id) is required for replay.")
        workflow: Workflow = self.repository.load(workflow_id)

        if run_id and hasattr(self.repository, "directory"):
            run_dir = self.repository.directory / run_id
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                snapshot_path = run_dir / f"{workflow_id}_workflow.json"
                snapshot_path.write_text(
                    workflow.model_dump_json(indent=2), encoding="utf-8"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Failed to snapshot workflow to run directory %s: %s",
                    run_dir,
                    e,
                )

        async def on_step_update(step_num: int, action: Action) -> None:
            if run_id and self.run_history_repository:
                self.run_history_repository.save_step(
                    run_id=run_id,
                    step_number=step_num,
                    action_type=action.action_type,
                    status=action.status.value,
                    goal=action.goal,
                    started_at=action.started_at,
                    finished_at=action.finished_at,
                )
            self.repository.save(workflow)

        # Run standard Playwright context
        async with async_playwright() as p:
            if self.browser_config.cdp_url:
                logger.info(
                    f"Connecting Playwright replayer to CDP: {self.browser_config.cdp_url}"
                )
                browser: PlaywrightBrowser = await p.chromium.connect_over_cdp(
                    self.browser_config.cdp_url
                )
                context: PlaywrightContext = browser.contexts[0]
                page: PlaywrightPage = (
                    context.pages[0] if context.pages else await context.new_page()
                )
            else:
                browser = await p.chromium.launch(headless=self.browser_config.headless)
                context = await browser.new_context()
                page = await context.new_page()

            adapter: PlaywrightAdapter = PlaywrightAdapter(page, self.link)
            # Execute workflow with safety verifications
            await adapter.execute_workflow(workflow, on_step_update=on_step_update)

            if not self.browser_config.cdp_url:
                await browser.close()

        # Retrieve final action result
        final_action: Action = workflow.actions[-1]
        if isinstance(final_action, DoneAction):
            return final_action.text
        return "Workflow completed."
