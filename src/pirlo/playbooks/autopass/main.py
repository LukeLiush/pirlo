# src/pirlo/playbooks/autopass/main.py
from __future__ import annotations

from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.ports.play import Play
from pirlo.infrastructure.services.profile_manager import ProfileManager
from pirlo.playbooks.autopass.models import (
    AutopassRunOutput,
    SubtaskExecutionOutput,
)
from pirlo.playbooks.autopass.subplaybooks import (
    DecomposeTaskPlay,
    ExecuteSubtaskPlay,
    MergeResultsPlay,
    QuickProgressListener,
)

__all__ = ["AutopassSession", "QuickProgressListener"]


@play(
    name="autopass",
    description="Run self-healing decomposed browser automation workflows.",
)
class AutopassSession(Play[AutopassRunOutput]):
    """Top-level Autopass orchestration Play executing decomposed subtasks."""

    async def execute(
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
    ) -> AutopassRunOutput:
        if not ProfileManager.exists(profile):
            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=profile, existing_info=""
            )
            self.ui.yellow_card(instruction)
            raise ValueError(str(instruction))

        if not task:
            self.ui.yellow_card(AutopassInstructions.TASK_REQUIRED)
            raise ValueError(str(AutopassInstructions.TASK_REQUIRED))

        self.ui.header("Autopass Execution", subtitle=f"Task: {task}")

        # ---------------------------------------------------------------------
        # Step 1: Decompose task into subtasks
        # ---------------------------------------------------------------------
        decomposer = DecomposeTaskPlay(ui=self.ui)
        decomp_output = await decomposer.execute(
            task_prompt=task,
            playmaker=playmaker,
        )

        # ---------------------------------------------------------------------
        # Step 2: Execute subtasks sequentially
        # ---------------------------------------------------------------------
        executor = ExecuteSubtaskPlay(ui=self.ui)
        subtask_results: list[SubtaskExecutionOutput] = []
        for subtask_prompt in decomp_output.task_prompts:
            sub_res = await executor.execute(
                subtask_prompt=subtask_prompt,
                profile=profile,
                headless=headless,
                playmaker=playmaker,
                use_vision=use_vision,
            )
            subtask_results.append(sub_res)

        # ---------------------------------------------------------------------
        # Step 3: Merge results into final output
        # ---------------------------------------------------------------------
        merger = MergeResultsPlay(ui=self.ui)
        return await merger.execute(
            original_task=task,
            subtask_results=subtask_results,
        )


if __name__ == "__main__":
    AutopassSession.cli()
