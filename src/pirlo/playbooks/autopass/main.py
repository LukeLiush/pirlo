# src/pirlo/playbooks/autopass/main.py
from __future__ import annotations

from typing import Annotated

from pirlo.core.decorators import playbook
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
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
    ) -> PlayerNode:
        if not ProfileManager.exists(profile):
            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=profile, existing_info=""
            )
            self.ui.yellow_card(instruction)
            raise ValueError(str(instruction))

        if not task:
            self.ui.yellow_card(AutopassInstructions.TASK_REQUIRED)
            raise ValueError(str(AutopassInstructions.TASK_REQUIRED))

        # ---------------------------------------------------------------------
        # Step 1: Draft task_decomposer
        # ---------------------------------------------------------------------
        task_decomposer: PlayerNode = self.player(
            DecomposeTaskPlaybook,
            task_prompt=task,
            playmaker=playmaker,
        )

        # ---------------------------------------------------------------------
        # Step 2: Draft subtask_executors using each(...) for dynamic fan-out
        # ---------------------------------------------------------------------
        subtask_executors: PlayerNode = self.player(
            ExecuteSubtaskPlaybook,
            subtask_prompt=each(task_decomposer.ball.task_prompts),
            profile=profile,
            headless=headless,
            playmaker=playmaker,
            use_vision=use_vision,
        )

        # ---------------------------------------------------------------------
        # Step 3: Draft result_summarizer (implicit dataflow + terminal return)
        # ---------------------------------------------------------------------
        return self.player(
            MergeResultsPlaybook,
            original_task=task,
            subtask_results=subtask_executors.ball,
        )


if __name__ == "__main__":
    AutopassSession.cli()
