import importlib.metadata
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime

from browser_use import Agent, Browser
from browser_use.agent.views import AgentHistoryList

from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.workflow import Workflow, WorkflowMetadata
from pirlo.core.ports.run_history import RunHistoryRepository
from pirlo.core.repository.workflow import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    BrowserAgentFactory,
)
from pirlo.infrastructure.services.workflow_service import (
    convert_history_to_workflow,
    generate_deterministic_id,
)

logger = logging.getLogger(__name__)


class LlmWorkflowRunner(WorkflowRunner):
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
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        if not workflow_id:
            workflow_id = generate_deterministic_id(task_prompt)

        # Launch browser-use agent
        browser: Browser = Browser(
            cdp_url=self.browser_config.cdp_url,
            headless=self.browser_config.headless,
        )
        agent: Agent = self.agent_factory.create_agent(task_prompt, browser)

        started_dt = datetime.now(UTC)
        if run_id and self.run_history_repository:
            self.run_history_repository.save_step(
                run_id=run_id,
                step_number=1,
                action_type="llm_execution",
                status="running",
                goal=task_prompt,
                started_at=started_dt,
            )

        try:
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

            if run_id and self.run_history_repository:
                self.run_history_repository.save_step(
                    run_id=run_id,
                    step_number=1,
                    action_type="llm_execution",
                    status="completed",
                    goal=task_prompt,
                    started_at=started_dt,
                    finished_at=datetime.now(UTC),
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
            await browser.close()
