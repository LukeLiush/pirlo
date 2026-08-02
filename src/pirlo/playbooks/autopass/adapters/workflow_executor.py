import logging
import os
from pathlib import Path

from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    DefaultBrowserAgentFactory,
)
from pirlo.infrastructure.repository import JsonFileWorkflowRepository
from pirlo.infrastructure.services.llm_workflow import LlmWorkflowRunner
from pirlo.infrastructure.services.playwright_workflow import PlaywrightReplayRunner
from pirlo.infrastructure.services.self_healing_workflow import SelfHealingRunner
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory
from pirlo.playbooks.autopass.core.ports import WorkflowExecutor

PIRLO_WORKSPACE = Path(os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")).expanduser()

logger = logging.getLogger("autopass.workflow")


class SelfHealingWorkflowExecutor(WorkflowExecutor):
    """Adapter executing workflows via Pirlo's SelfHealingRunner."""

    def __init__(self, cdp_url: str, config: dict):
        self.cdp_url = cdp_url
        self.config = config

    async def execute(self, task_prompt: str) -> str:
        runs_dir = PIRLO_WORKSPACE / "autopass" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        repository = JsonFileWorkflowRepository(directory=runs_dir)

        # Configure browser config to connect over CDP
        browser_config = BrowserConfig(cdp_url=self.cdp_url)

        playmaker_link: LlmLink | None = self.config.get("playmaker")
        if not playmaker_link or not isinstance(playmaker_link, LlmLink):
            raise ValueError(
                "Playmaker link parameter ('playmaker') must be a valid LlmLink object."
            )

        analyst_link: LlmLink | None = self.config.get("analyst")
        if not analyst_link or not isinstance(analyst_link, LlmLink):
            raise ValueError(
                "Analyst link parameter ('analyst') must be a valid LlmLink object."
            )

        transform_llm = LlmFactory.create_langchain_llm(
            link=analyst_link,
            temperature=0.0,
            timeout=120.0,
        )

        thinking_llm = LlmFactory.create_browser_use_llm(
            link=playmaker_link,
            temperature=0.0,
            timeout=120.0,
        )

        # Instantiate concrete Runners
        replay_runner = PlaywrightReplayRunner(
            repository=repository,
            llm=transform_llm,
            browser_config=browser_config,
        )

        agent_factory = DefaultBrowserAgentFactory(
            llm=thinking_llm,
            use_vision=self.config.get("use_vision", False),
            max_failures=self.config.get("max_failures", 5),
            retry_delay=self.config.get("retry_delay", 10),
        )

        fallback_runner = LlmWorkflowRunner(
            agent_factory=agent_factory,
            repository=repository,
            browser_config=browser_config,
        )

        autopass_runner = SelfHealingRunner(
            replay_runner=replay_runner,
            fallback_runner=fallback_runner,
            repository=repository,
        )

        result = await autopass_runner.run(task_prompt=task_prompt)
        logger.info("Workflow execution completed. Result: %s", result)
        return result
