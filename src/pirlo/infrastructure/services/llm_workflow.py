import hashlib
import importlib.metadata
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime

from browser_use import Agent, BrowserSession
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.events import SwitchTabEvent
from playwright.async_api import Page as PlaywrightPage

from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.execution_context import DEFAULT_CONTEXT, ExecutionContext
from pirlo.core.models.workflow import Workflow, WorkflowMetadata
from pirlo.core.repository.run_history_repository import RunHistoryRepository
from pirlo.core.repository.workflow_repository import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    BrowserAgentFactory,
)
from pirlo.infrastructure.services.workflow_service import (
    convert_history_to_workflow,
)

logger = logging.getLogger(__name__)


class LlmWorkflowRunner(WorkflowRunner[PlaywrightPage]):
    """Automates a web task via LLM-driven browser-use Agent and persists execution steps to cache."""

    agent_factory: BrowserAgentFactory
    repository: WorkflowRepository
    browser_config: BrowserConfig
    run_history_repository: RunHistoryRepository | None

    def __init__(
        self,
        agent_factory: BrowserAgentFactory,
        repository: WorkflowRepository,
        browser_config: BrowserConfig,
        run_history_repository: RunHistoryRepository | None = None,
    ) -> None:
        self.agent_factory = agent_factory
        self.repository = repository
        self.browser_config = browser_config
        self.run_history_repository = run_history_repository

    def _build_metadata(
        self, agent: Agent, task_prompt: str, elapsed: float
    ) -> WorkflowMetadata:
        """Extracts runtime metadata dynamically from the agent and execution context."""
        # Extract creator Info
        creator = agent.__module__
        if "." in creator:
            creator = creator.split(".")[0]
        try:
            creator_version = importlib.metadata.version(creator.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            creator_version = "unknown"

        # Extract browser Info
        browser_version = "unknown"
        browser_type = "chrome"

        llm_provider, llm_model_name = self.agent_factory.get_llm_metadata()

        git_commit_sha = None
        try:
            git_commit_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Failed to retrieve git commit SHA: {e}")

        return WorkflowMetadata(
            creator=creator,
            creator_version=creator_version,
            browser_type=browser_type,
            browser_version=browser_version,
            created_at=datetime.now(UTC).isoformat(),
            original_task_prompt=task_prompt,
            execution_duration_seconds=elapsed,
            llm_provider=llm_provider,
            llm_model_name=llm_model_name,
            os_platform=sys.platform,
            git_commit_sha=git_commit_sha,
        )

    async def run(
        self,
        task_prompt: str,
        context: ExecutionContext[PlaywrightPage] = DEFAULT_CONTEXT,
    ) -> str:
        page = context.page
        if page is None:
            raise ValueError(
                "LlmWorkflowRunner requires an active page in the ExecutionContext"
            )
        if not self.browser_config.cdp_url:
            raise ValueError(
                "LlmWorkflowRunner requires a CDP URL in the BrowserConfig"
            )
        cache_key = context.cache_key
        run_id = context.run_id
        workflow_id = cache_key or hashlib.sha256(task_prompt.encode()).hexdigest()[:16]

        browser: BrowserSession = BrowserSession(
            cdp_url=self.browser_config.cdp_url,
            headless=self.browser_config.headless,
        )
        target_id: str = await self._target_id_for_page(page)
        await browser.start()
        started_dt = datetime.now(UTC)
        try:
            evt = browser.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
            await evt
            await evt.event_result(raise_if_any=True, raise_if_none=False)

            agent = self.agent_factory.create_agent(task_prompt, browser=browser)

            if run_id and self.run_history_repository:
                self.run_history_repository.save_step(
                    run_id=run_id,
                    step_number=1,
                    action_type="llm_execution",
                    status="running",
                    goal=task_prompt,
                    started_at=started_dt,
                )

            logger.info("Agent run started...")
            start_time = time.time()
            history: AgentHistoryList = await agent.run()
            elapsed = time.time() - start_time

            # Extract runtime metadata
            metadata: WorkflowMetadata = self._build_metadata(
                agent, task_prompt, elapsed
            )

            # Map history to domain workflow
            workflow: Workflow = convert_history_to_workflow(
                history_list=history,
                workflow_id=workflow_id,
                description=task_prompt,
                metadata=metadata,
            )

            # Save workflow representation to cache repo
            self.repository.save(workflow)

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

            if run_id and self.run_history_repository:
                for idx, action in enumerate(workflow.actions):
                    step_num = (
                        action.step_number
                        if action.step_number is not None
                        else (idx + 1)
                    )
                    self.run_history_repository.save_step(
                        run_id=run_id,
                        step_number=step_num,
                        action_type=action.action_type,
                        status=action.status.value
                        if hasattr(action.status, "value")
                        else str(action.status),
                        goal=action.goal,
                    )

            return history.final_result() or "Workflow finished."
        except Exception:
            if run_id and self.run_history_repository:
                self.run_history_repository.save_step(
                    run_id=run_id,
                    step_number=1,
                    action_type="llm_execution",
                    status="failed",
                    goal=task_prompt,
                    started_at=started_dt,
                    finished_at=datetime.now(UTC),
                )
            raise
        finally:
            await browser.stop()

    async def _target_id_for_page(self, page: PlaywrightPage) -> str:
        cdp = await page.context.new_cdp_session(page)
        try:
            info = await cdp.send("Target.getTargetInfo")
            return info["targetInfo"]["targetId"]
        finally:
            await cdp.detach()
