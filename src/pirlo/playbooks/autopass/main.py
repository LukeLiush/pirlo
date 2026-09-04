# src/pirlo/playbooks/autopass/main.py
from __future__ import annotations

from typing import Annotated, cast

from pirlo.core.decorators import playbook
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.blueprint import PlaybookOutput
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import PreparedRun, RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.playbook import Playbook, PlayerNode, each
from pirlo.infrastructure.services.profile_manager import ProfileManager
from pirlo.playbooks.autopass.models import (
    AutopassRunOutput,
)
from pirlo.playbooks.autopass.subplaybooks import (
    DecomposeTaskPlaybook,
    ExecuteSubtaskPlaybook,
    MergeResultsPlaybook,
    QuickProgressListener,
)

__all__ = ["AutopassSession", "QuickProgressListener"]


@playbook(
    name="autopass",
    description="Run self-healing decomposed browser automation workflows.",
)
class AutopassSession(Playbook[AutopassRunOutput]):
    """Top-level Autopass orchestration Pitch executing decomposed subtasks."""

    async def play(
        self,
        profile: Annotated[str, Parameter(help="Browser profile name")] = "default",
        headless: Annotated[
            bool, Parameter(help="Run browser in headless mode")
        ] = False,
        task: Annotated[
            str, Parameter(help="Task prompt to execute autonomously")
        ] = "",
        playmaker: Annotated[
            LlmLink | None, LinkParameter(help="Playmaker LLM link")
        ] = None,
        use_vision: Annotated[
            bool, Parameter(help="Enable vision for the Agent")
        ] = False,
        max_failures: Annotated[
            int, Parameter(help="Max consecutive step failures allowed")
        ] = 3,
        retry_delay: Annotated[
            int, Parameter(help="Delay in seconds between retries")
        ] = 5,
        *args: object,
        **kwargs: object,
    ) -> AutopassRunOutput | RunResult[AutopassRunOutput]:
        prepared: PreparedRun | None = None
        try:
            prepared = await self.prepared_run()
        except RuntimeError:
            prepared = None

        if not ProfileManager.exists(profile):
            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=profile, existing_info=""
            )
            self.ui.yellow_card(instruction)
            return RunResult(
                run_id=prepared.run_id if prepared else "unknown",
                status=RunStatus.FAILED,
                error=str(instruction),
            )

        if not task:
            self.ui.yellow_card(AutopassInstructions.TASK_REQUIRED)
            return RunResult(
                run_id=prepared.run_id if prepared else "unknown",
                status=RunStatus.FAILED,
                error=str(AutopassInstructions.TASK_REQUIRED),
            )

        # ---------------------------------------------------------------------
        # Step 1: Draft task_decomposer
        # ---------------------------------------------------------------------
        task_decomposer: PlayerNode = self.player(
            cast(type[Playbook[PlaybookOutput]], DecomposeTaskPlaybook),
            task_prompt=task,
            playmaker=playmaker,
        )

        # ---------------------------------------------------------------------
        # Step 2: Draft subtask_executors using each(...) for dynamic fan-out
        # ---------------------------------------------------------------------
        subtask_executors: PlayerNode = self.player(
            cast(type[Playbook[PlaybookOutput]], ExecuteSubtaskPlaybook),
            subtask_prompt=each(task_decomposer.ball.task_prompts),
            profile=profile,
            headless=headless,
            playmaker=playmaker,
            use_vision=use_vision,
        )

        # ---------------------------------------------------------------------
        # Step 3: Draft result_summarizer and wire DAG dependencies with '>>'
        # ---------------------------------------------------------------------
        result_summarizer: PlayerNode = self.player(
            cast(type[Playbook[PlaybookOutput]], MergeResultsPlaybook),
            original_task=task,
        )

        # Wire passing line: task_decomposer >> subtask_executors >> result_summarizer
        task_decomposer >> subtask_executors >> result_summarizer

        # Single static kickoff pass!
        final_output: AutopassRunOutput = cast(
            AutopassRunOutput,
            await self.kickoff(),
        )
        return final_output


if __name__ == "__main__":
    AutopassSession.cli()
