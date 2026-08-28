import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

from pirlo.core.config import get_workspace_path
from pirlo.core.decorators import playbook
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import PreparedRun, RunStatus
from pirlo.core.models.run_result import AutopassRunOutput, RunResult
from pirlo.core.ports.browser_agent_factory import BrowserAgentFactory
from pirlo.core.repository.workflow_repository import WorkflowRepository
from pirlo.core.services.workflow_runner import WorkflowRunner
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    DefaultBrowserAgentFactory,
)
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.infrastructure.repository.json_file_workflow_repository import (
    JsonFileWorkflowRepository,
)
from pirlo.infrastructure.services.llm_workflow import LlmWorkflowRunner
from pirlo.infrastructure.services.playwright_workflow import PlaywrightReplayRunner
from pirlo.infrastructure.services.profile_manager import ProfileManager
from pirlo.infrastructure.services.self_healing_workflow import SelfHealingRunner
from pirlo.playbooks.autopass.adapters.browser_manager import CloakBrowserManager
from pirlo.playbooks.autopass.adapters.cdp_checker import HttpCdpConnectionChecker
from pirlo.playbooks.autopass.core.ports import (
    BrowserManager,
    CdpChecker,
    ProgressListener,
)
from pirlo.playbooks.autopass.core.use_cases import RunAutopassUseCase

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


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


@playbook(name="autopass", description="Run self-healing browser automation workflows.")
class AutopassSession(TerminalPitch):
    """Run self-healing browser automation workflows."""

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
        analyst: Annotated[
            LlmLink | None,
            LinkParameter(
                help="Link name for Analyst (DOM summary / selector healer)",
                env_name="ANALYST",
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
        schedule: Annotated[
            str | None,
            Parameter(
                help="Optional schedule preset or raw cron string",
                env_name="SCHEDULE",
                short="-s",
            ),
        ] = None,
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[AutopassRunOutput]:
        self.header(
            "Autopass Workflow Pitch",
            subtitle="Autonomous Browser Automation",
        )

        if not ProfileManager.exists(profile):
            all_profiles = ProfileManager.list_profiles()
            if all_profiles:
                profiles_info = "Existing Saved Profiles:\n" + "\n".join(
                    f"  • {p.name} (URLs: {', '.join(p.authenticated_urls) or 'None'})"
                    for p in all_profiles
                )
            else:
                profiles_info = "No browser profiles currently exist."

            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=profile, existing_info=profiles_info
            )
            self.yellow_card(instruction)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=str(instruction),
            )

        if ProfileManager.is_expired(profile):
            meta = ProfileManager.load_profile_metadata(profile)
            exp_date = meta.expires_at if meta else "N/A"
            ttl_days = meta.ttl_days if meta else 7
            days_passed = ProfileManager.get_days_since_created(profile)
            urls_str = (
                " ".join(meta.authenticated_urls)
                if (meta and meta.authenticated_urls)
                else "<target_urls>"
            )
            instruction = AutopassInstructions.PROFILE_EXPIRED.format(
                profile=profile,
                days_passed=days_passed,
                ttl_days=ttl_days,
                expires_at=exp_date,
                authenticated_urls=urls_str,
            )
            self.yellow_card(instruction)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=str(instruction),
            )

        profile_path: Path = ProfileManager.resolve_profile_path(profile)

        if not task:
            self.yellow_card(AutopassInstructions.TASK_REQUIRED)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=str(AutopassInstructions.TASK_REQUIRED),
            )

        if playmaker is None or analyst is None:
            err_msg = (
                "Error: Playmaker and Analyst links are required.\n"
                "Please specify --playmaker and --analyst.\n"
                "Run 'pirlo link list' to see available links, or 'pirlo link create' to register a new one."
            )
            self.yellow_card(err_msg)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=err_msg,
            )

        pm_base_url = playmaker.base_url or "N/A"
        an_base_url = analyst.base_url or "N/A"

        self.lineup(
            "Active Run Configuration",
            columns=["Setting", "Value"],
            rows=[
                ["Profile Path", str(profile_path.resolve())],
                ["Headless", str(headless)],
                ["Task", task],
                [
                    "Playmaker Link (Provider)",
                    f"{playmaker} ({playmaker.provider})",
                ],
                ["Playmaker Model", playmaker.model],
                ["Playmaker Base URL", pm_base_url or "N/A"],
                [
                    "Analyst Link (Provider)",
                    f"{analyst} ({analyst.provider})",
                ],
                ["Analyst Model", analyst.model],
                ["Analyst Base URL", an_base_url or "N/A"],
                ["Vision Enabled", str(use_vision)],
                ["Max Failures / Delay", f"{max_failures} / {retry_delay}s"],
                [
                    "Orchestrator Backend",
                    getattr(
                        self.orchestrator,
                        "orchestrator_name",
                        self.orchestrator.__class__.__name__,
                    )
                    if self.orchestrator
                    else "prefect",
                ],
                ["Schedule", schedule or "None (Immediate)"],
            ],
        )

        workflows_dir: Path = get_workspace_path() / "workflows"
        workflow_repo: WorkflowRepository = JsonFileWorkflowRepository(workflows_dir)
        browser_config: BrowserConfig = BrowserConfig(
            cdp_url=CDP_URL, headless=headless
        )

        agent_factory: BrowserAgentFactory = DefaultBrowserAgentFactory(
            link=playmaker,
            use_vision=use_vision,
            max_failures=max_failures,
            retry_delay=retry_delay,
        )

        fallback_runner: WorkflowRunner = LlmWorkflowRunner(
            agent_factory=agent_factory,
            repository=workflow_repo,
            browser_config=browser_config,
        )

        replay_runner: WorkflowRunner = PlaywrightReplayRunner(
            repository=workflow_repo,
            link=analyst,
            browser_config=browser_config,
        )

        self_healing_runner: WorkflowRunner = SelfHealingRunner(
            replay_runner=replay_runner,
            fallback_runner=fallback_runner,
            repository=workflow_repo,
        )

        browser_manager: BrowserManager = CloakBrowserManager()
        cdp_checker: CdpChecker = HttpCdpConnectionChecker(CDP_URL)
        run_autopass_use_case: RunAutopassUseCase = RunAutopassUseCase(
            browser_manager=browser_manager,
            cdp_checker=cdp_checker,
            workflow_runner=self_healing_runner,
        )
        prepared: PreparedRun = await self.prepared_run()

        async def run_use_case(
            task_prompt: str | None = None, site: str | None = None, **kwargs: Any
        ) -> str:
            effective_task = task_prompt or task
            return await run_autopass_use_case.run(
                task_prompt=effective_task,
                profile_path=profile_path,
                headless=headless,
                cdp_port=CDP_PORT,
                listener=QuickProgressListener(),
                run_name=prepared.run_name,
                run_id=prepared.run_id,
            )

        raw_output = await self.orchestrator.execute(
            prepared, run_use_case, task=task, schedule=schedule
        )

        autopass_output: AutopassRunOutput = AutopassRunOutput(
            task_prompt=task,
            final_message=str(raw_output),
        )

        return RunResult(
            run_id=prepared.run_id,
            status=RunStatus.COMPLETED,
            data=autopass_output,
        )


if __name__ == "__main__":
    AutopassSession.cli()
