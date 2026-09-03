# src/pirlo/playbooks/autopass/main.py
from __future__ import annotations

from typing import Annotated

from pirlo.core.decorators import playbook
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import PreparedRun, RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.pitch import Pitch, PlayerNode
from pirlo.infrastructure.services.profile_manager import ProfileManager
from pirlo.playbooks.autopass.models import (
    AutopassRunOutput,
    TaskDecompositionOutput,
)
from pirlo.playbooks.autopass.subplaybooks import (
    DecomposeTaskPlaybook,
    ExecuteSubtaskPlaybook,
    MergeResultsPlaybook,
    QuickProgressListener,
)

Playbook = Pitch
__all__ = ["AutopassSession", "QuickProgressListener"]


@playbook(name="autopass", description="Run self-healing decomposed browser automation workflows.")
class AutopassSession(Playbook[AutopassRunOutput]):
    """Run self-healing browser automation workflows decomposed into a multi-step DAG."""

    async def play(
            self,
            profile: Annotated[
                str,
                Parameter(
                    help="Name or path of the browser profile to use (default: 'default')",
                    env_name="PROFILE",
                ),
            ] = "default",
            headless: Annotated[
                bool, Parameter(help="Run browser in headless mode", env_name="HEADLESS")
            ] = False,
            task: Annotated[
                str, Parameter(help="Task prompt to execute autonomously", env_name="TASK")
            ] = "",
            playmaker: Annotated[
                LlmLink | None,
                LinkParameter(
                    help="Link name for Playmaker (decision brain)", env_name="PLAYMAKER"
                ),
            ] = None,
            use_vision: Annotated[
                bool, Parameter(help="Enable vision for the Agent", env_name="USE_VISION")
            ] = False,
            max_failures: Annotated[
                int,
                Parameter(
                    help="Maximum failure attempts before stopping", env_name="MAX_FAILURES"
                ),
            ] = 5,
            retry_delay: Annotated[
                int, Parameter(help="Retry delay in seconds", env_name="RETRY_DELAY")
            ] = 10,
            *args: object,
            **kwargs: object,
    ) -> AutopassRunOutput | RunResult[AutopassRunOutput]:
        prepared: PreparedRun | None = None
        try:
            prepared = await self.prepared_run()
        except RuntimeError:
            pass

        self.ui.header(
            "Autopass Workflow Pitch",
            subtitle="Autonomous Decomposed Browser Automation",
        )

        if not ProfileManager.exists(profile):
            all_profiles = ProfileManager.list_profiles()
            profiles_info = (
                "Existing Saved Profiles:\n"
                + "\n".join(
                    f"  • {p.name} (URLs: {', '.join(p.authenticated_urls) or 'None'})"
                    for p in all_profiles
                )
                if all_profiles
                else "No browser profiles currently exist."
            )
            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=profile, existing_info=profiles_info
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
        # Phase 1: Run task_decomposer to get actual Python list of prompt strings
        # ---------------------------------------------------------------------
        task_decomposer: PlayerNode = self.player(
            DecomposeTaskPlaybook,
            task_prompt=task,
            playmaker=playmaker,
        )
        decomp_output: Any = await self.kickoff([task_decomposer])
        prompts: list[str] = (
            decomp_output.task_prompts
            if hasattr(decomp_output, "task_prompts") and decomp_output.task_prompts
            else [task]
        )

        # ---------------------------------------------------------------------
        # Phase 2: Draft ONE ExecuteSubtaskPlaybook node for EACH prompt string!
        # ---------------------------------------------------------------------
        subtask_executors: list[PlayerNode] = [
            self.player(
                ExecuteSubtaskPlaybook,
                subtask_prompt=prompt_string,
                profile=profile,
                headless=headless,
                playmaker=playmaker,
                use_vision=use_vision,
            )
            for prompt_string in prompts
        ]

        # ---------------------------------------------------------------------
        # Phase 3: Draft result_summarizer and wire dependencies using '>>'!
        # ---------------------------------------------------------------------
        result_summarizer: PlayerNode = self.player(
            MergeResultsPlaybook,
            original_task=task,
        )

        # Wire dependency line: list of subtask_executors pass to result_summarizer
        subtask_executors >> result_summarizer

        # Kickoff Phase 2: run subtask_executors and result_summarizer!
        final_output: AutopassRunOutput = await self.kickoff(
            [*subtask_executors, result_summarizer]
        )
        return final_output


if __name__ == "__main__":
    AutopassSession.cli()
