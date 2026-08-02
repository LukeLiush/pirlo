import logging

from langchain_core.language_models.chat_models import BaseChatModel
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightContext
from playwright.async_api import Page as PlaywrightPage
from playwright.async_api import async_playwright

from pirlo.core.models.actions import Action, DoneAction
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.workflow import Workflow
from pirlo.core.repository.workflow import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.core.ports.run_history import RunHistoryRepository
from pirlo.infrastructure.adapters.browser.playwright_adapter import PlaywrightAdapter
from pirlo.infrastructure.services.workflow_service import generate_deterministic_id

logger = logging.getLogger(__name__)


class PlaywrightReplayRunner(WorkflowRunner):
    """Executes a cached domain Workflow sequence deterministically using standard Playwright."""

    repository: WorkflowRepository
    llm: BaseChatModel | None
    browser_config: BrowserConfig
    run_history_repository: RunHistoryRepository | None

    def __init__(
        self,
        repository: WorkflowRepository,
        llm: BaseChatModel | None,
        browser_config: BrowserConfig,
        run_history_repository: RunHistoryRepository | None = None,
    ) -> None:
        self.repository = repository
        self.llm = llm
        self.browser_config = browser_config
        self.run_history_repository = run_history_repository

    async def run(
        self,
        task_prompt: str,
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        if not workflow_id:
            workflow_id = generate_deterministic_id(task_prompt)

        # Load from repository boundary
        workflow: Workflow = self.repository.load(workflow_id)

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

            adapter: PlaywrightAdapter = PlaywrightAdapter(page, self.llm)
            # Execute workflow with safety verifications
            await adapter.execute_workflow(workflow, on_step_update=on_step_update)

            if not self.browser_config.cdp_url:
                await browser.close()

        # Retrieve final action result
        final_action: Action = workflow.actions[-1]
        if isinstance(final_action, DoneAction):
            return final_action.text
        return "Workflow completed."
