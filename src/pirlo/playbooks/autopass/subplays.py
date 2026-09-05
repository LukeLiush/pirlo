# src/pirlo/playbooks/autopass/subplays.py
from __future__ import annotations

import logging
import socket
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated, Any, cast

from pirlo.core.config import get_workspace_path
from pirlo.core.decorators import play
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.ports.browser_agent_factory import BrowserAgentFactory
from pirlo.core.ports.play import Play, requires
from pirlo.core.repository.workflow_repository import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    DefaultBrowserAgentFactory,
)
from pirlo.infrastructure.adapters.decomposer.pydantic_ai_decomposer import (
    PydanticAiDecomposer,
)
from pirlo.infrastructure.repository.json_file_workflow_repository import (
    JsonFileWorkflowRepository,
)
from pirlo.infrastructure.services.llm_workflow import LlmWorkflowRunner
from pirlo.infrastructure.services.playwright_workflow import PlaywrightReplayRunner
from pirlo.infrastructure.services.profile_manager import ProfileManager
from pirlo.infrastructure.services.self_healing_workflow import SelfHealingRunner
from pirlo.playbooks.autopass.adapters.browser_manager import CloakBrowserManager
from pirlo.playbooks.autopass.core.ports import ProgressListener
from pirlo.playbooks.autopass.core.use_cases import RunAutopassUseCase
from pirlo.playbooks.autopass.models import (
    AutopassRunOutput,
    SubtaskExecutionOutput,
    TaskDecompositionOutput,
)

logger = logging.getLogger(__name__)
CDP_PORT = 9222


class QuickProgressListener(ProgressListener):
    """Port for presenting status updates and notifications to the user."""

    @contextmanager
    def status_context(self, message: str) -> Generator[None, None, None]:
        print(f"⏳ {message}")
        try:
            yield
        finally:
            pass

    def show_warning(self, message: Any, detail: str | None = None) -> None:
        sys.stderr.write(f"⚠️ Warning: {message}\n")

    def show_goal(self, message: str, detail: str | None = None) -> None:
        print(f"⚽ GOAL: {message}")
        if detail:
            print(f"   Detail: {detail}")

    def show_red_card(self, message: str, detail: str | None = None) -> None:
        sys.stderr.write(f"🟥 Error: {message}\n")
        if detail:
            sys.stderr.write(f"   Detail: {detail}\n")


QuietProgressListener = QuickProgressListener


def find_free_port() -> int:
    """Finds an available ephemeral TCP port assigned by the OS kernel."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return cast(int, s.getsockname()[1])


@play(
    name="autopass_decompose",
    description="Decomposes user task prompt into discrete subtask steps",
)
class DecomposeTaskPlay(Play[TaskDecompositionOutput]):
    async def execute(
        self,
        task: Annotated[str, Parameter(help="Task prompt to decompose")] = "",
        task_prompt: Annotated[str, Parameter(help="Task prompt alias")] = "",
        playmaker: Annotated[
            LlmLink | None, LinkParameter(help="Playmaker LLM link")
        ] = None,
    ) -> TaskDecompositionOutput:
        effective_prompt = task or task_prompt
        if not effective_prompt:
            return TaskDecompositionOutput(task_prompts=[], total_subtasks=0)

        if playmaker is not None:
            decomposer = PydanticAiDecomposer(link=playmaker)
            try:
                plan: Any = await decomposer.decompose(effective_prompt)
                subtasks = plan.subtasks if hasattr(plan, "subtasks") else plan
                prompts = [
                    getattr(s, "task_prompt", str(s))
                    for s in subtasks
                    if getattr(s, "task_prompt", str(s)).strip()
                ]
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    f"LLM task decomposition failed, falling back to direct prompt: {err}"
                )
                prompts = [effective_prompt]
        else:
            prompts = [effective_prompt]

        if not prompts:
            prompts = [effective_prompt]

        return TaskDecompositionOutput(
            task_prompts=prompts, total_subtasks=len(prompts)
        )


@play(
    name="autopass_execute_subtask",
    description="Executes browser automation for ONE single subtask prompt",
)
class ExecuteSubtaskPlay(Play[SubtaskExecutionOutput]):
    subtask_prompt: str = requires(DecomposeTaskPlay, each="task_prompts")

    async def execute(
        self,
        subtask_prompt: Annotated[
            str, Parameter(help="Single subtask prompt string to execute")
        ] = "",
        profile: Annotated[str, Parameter(help="Browser profile name")] = "default",
        headless: Annotated[
            bool, Parameter(help="Run browser in headless mode")
        ] = False,
        playmaker: Annotated[
            LlmLink | None, LinkParameter(help="Playmaker LLM link")
        ] = None,
        use_vision: Annotated[
            bool, Parameter(help="Enable vision for the Agent")
        ] = False,
    ) -> SubtaskExecutionOutput:
        prompt = subtask_prompt or getattr(self, "subtask_prompt", "")
        if not prompt:
            return SubtaskExecutionOutput(
                subtask_prompt="",
                result_message="Empty subtask prompt provided.",
                success=False,
            )

        cdp_port = find_free_port()
        profile_path = ProfileManager.resolve_profile_path(profile)
        workflows_dir = get_workspace_path() / "workflows"
        workflow_repo: WorkflowRepository = JsonFileWorkflowRepository(workflows_dir)
        browser_config = BrowserConfig(
            cdp_url=f"http://localhost:{cdp_port}", headless=headless
        )

        from pirlo.infrastructure.adapters.storage.composite_link_repository import (
            CompositeLinkRepository,
        )

        active_link = (
            playmaker
            or CompositeLinkRepository().get_by_name("playmaker")
            or LlmLink(
                name="default",
                provider="ollama",
                model="qwen2.5:latest",
                api_key="dummy",
            )
        )
        agent_factory: BrowserAgentFactory = DefaultBrowserAgentFactory(
            link=active_link,
            use_vision=use_vision,
        )

        fallback_runner: WorkflowRunner = LlmWorkflowRunner(
            agent_factory=agent_factory,
            repository=workflow_repo,
            browser_config=browser_config,
        )
        replay_runner: WorkflowRunner = PlaywrightReplayRunner(
            repository=workflow_repo,
            browser_config=browser_config,
        )
        self_healing_runner: WorkflowRunner = SelfHealingRunner(
            replay_runner=replay_runner,
            fallback_runner=fallback_runner,
            repository=workflow_repo,
        )
        browser_manager = CloakBrowserManager(
            profile_path=profile_path,
            headless=headless,
            cdp_port=cdp_port,
        )
        run_autopass_use_case = RunAutopassUseCase(workflow_runner=self_healing_runner)

        try:
            async with browser_manager.session() as session:
                msg = await run_autopass_use_case.run(
                    browser_manager=session,
                    task_prompt=prompt,
                    listener=QuietProgressListener(),
                    run_name="subtask_execution",
                    run_id="subtask_run",
                )
                return SubtaskExecutionOutput(
                    subtask_prompt=prompt,
                    result_message=str(msg),
                    success=True,
                )
        except Exception as err:  # noqa: BLE001
            return SubtaskExecutionOutput(
                subtask_prompt=prompt,
                result_message=f"Subtask execution failed: {err}",
                success=False,
            )


@play(
    name="autopass_merge_results",
    description="Merges subtask execution results into final report",
)
class MergeResultsPlay(Play[AutopassRunOutput]):
    async def execute(
        self,
        original_task: Annotated[
            str, Parameter(help="Original high-level task prompt")
        ] = "",
        subtask_results: Annotated[
            list[SubtaskExecutionOutput] | None,
            Parameter(help="List of subtask execution outputs"),
        ] = None,
    ) -> AutopassRunOutput:
        raw_list = subtask_results or []
        results_list: list[SubtaskExecutionOutput] = []
        for item in raw_list:
            if isinstance(item, list):
                results_list.extend(item)
            elif isinstance(item, SubtaskExecutionOutput):
                results_list.append(item)
        successful_count = sum(1 for s in results_list if s.success)
        total_count = len(results_list)

        details = "\n".join(
            f"  • Subtask '{s.subtask_prompt}': {s.result_message}"
            for s in results_list
        )
        final_msg = f"Task '{original_task}' completed ({successful_count}/{total_count} subtasks successful):\n{details}"

        return AutopassRunOutput(
            task_prompt=original_task,
            final_message=final_msg,
            subtask_results=results_list,
            actions_count=total_count,
        )
