import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pirlo.core.config import get_workspace_path
from pirlo.core.instructions import AutopassInstructions
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import AutopassRunOutput, RunResult
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
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory
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


class AutopassSession(TerminalPitch):
    """Run self-healing browser automation workflows."""

    profile = Parameter(
        str,
        default="default",
        help="Name or path of the browser profile to use (default: 'default')",
        env_name="PROFILE",
    )
    headless = Parameter(
        bool, default=False, help="Run browser in headless mode", env_name="HEADLESS"
    )
    task = Parameter(
        str,
        default=None,
        help=(
            "Task prompt to execute autonomously "
            '(e.g. "Go to google.com and search for OpenAI" or '
            '"Navigate to github.com and find trending Python repositories").'
        ),
        env_name="TASK",
    )
    playmaker = LinkParameter(
        help=(
            "Link name for Playmaker (decision brain). "
            "Use 'pirlo link list' to view registered link names, "
            "or 'pirlo link create <name>' to register a new link."
        ),
        env_name="PLAYMAKER",
    )
    analyst = LinkParameter(
        help=(
            "Link name for Analyst (DOM summary / selector healer). "
            "Use 'pirlo link list' to view registered link names, "
            "or 'pirlo link create <name>' to register a new link."
        ),
        env_name="ANALYST",
    )
    use_vision = Parameter(
        bool, default=False, help="Enable vision for the Agent", env_name="USE_VISION"
    )
    max_failures = Parameter(
        int,
        default=5,
        help="Maximum failure attempts before stopping",
        env_name="MAX_FAILURES",
    )
    retry_delay = Parameter(
        int, default=10, help="Retry delay in seconds", env_name="RETRY_DELAY"
    )

    async def on_play(self) -> RunResult[AutopassRunOutput]:
        self.header(
            "Autopass Workflow Pitch",
            subtitle="Autonomous Browser Automation",
        )

        if not ProfileManager.exists(self.profile):
            all_profiles = ProfileManager.list_profiles()
            if all_profiles:
                profiles_info = "Existing Saved Profiles:\n" + "\n".join(
                    f"  • {p.name} (URLs: {', '.join(p.authenticated_urls) or 'None'})"
                    for p in all_profiles
                )
            else:
                profiles_info = "No browser profiles currently exist."

            instruction = AutopassInstructions.PROFILE_MISSING.format(
                profile=self.profile, existing_info=profiles_info
            )
            self.yellow_card(instruction)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=str(instruction),
            )

        if ProfileManager.is_expired(self.profile):
            meta = ProfileManager.load_profile_metadata(self.profile)
            exp_date = meta.expires_at if meta else "N/A"
            ttl_days = meta.ttl_days if meta else 7
            days_passed = ProfileManager.get_days_since_created(self.profile)
            urls_str = (
                " ".join(meta.authenticated_urls)
                if (meta and meta.authenticated_urls)
                else "<target_urls>"
            )
            instruction = AutopassInstructions.PROFILE_EXPIRED.format(
                profile=self.profile,
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

        profile_path: Path = ProfileManager.resolve_profile_path(self.profile)

        if self.task is None:
            self.yellow_card(AutopassInstructions.TASK_REQUIRED)
            return RunResult(
                run_id=(await self.prepared_run()).run_id,
                status=RunStatus.FAILED,
                error=str(AutopassInstructions.TASK_REQUIRED),
            )

        if self.playmaker is None or self.analyst is None:
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

        # self.playmaker and self.analyst are resolved LlmLink domain objects
        pm_base_url = self.playmaker.base_url or "N/A"
        an_base_url = self.analyst.base_url or "N/A"

        self.lineup(
            "Active Run Configuration",
            columns=["Setting", "Value"],
            rows=[
                ["Profile Path", str(profile_path.resolve())],
                ["Headless", str(self.headless)],
                ["Task", self.task],
                [
                    "Playmaker Link (Provider)",
                    f"{self.playmaker} ({self.playmaker.provider})",
                ],
                ["Playmaker Model", self.playmaker.model],
                ["Playmaker Base URL", pm_base_url or "N/A"],
                [
                    "Analyst Link (Provider)",
                    f"{self.analyst} ({self.analyst.provider})",
                ],
                ["Analyst Model", self.analyst.model],
                ["Analyst Base URL", an_base_url or "N/A"],
                ["Vision Enabled", str(self.use_vision)],
                ["Max Failures / Delay", f"{self.max_failures} / {self.retry_delay}s"],
                [
                    "Orchestrator Backend",
                    getattr(self.orchestrator, "name", str(self.orchestrator))
                    if self.orchestrator
                    else "prefect",
                ],
                ["Schedule", self.schedule or "None (Immediate)"],
            ],
        )

        # 1. Create LLM instances from LlmLink objects via LlmFactory
        playmaker_llm = LlmFactory.create_langchain_llm(self.playmaker)
        analyst_llm = LlmFactory.create_langchain_llm(self.analyst)

        # 2. Initialize workflow repository and browser configuration
        workflows_dir = get_workspace_path() / ".pirlo" / "workflows"
        workflow_repo = JsonFileWorkflowRepository(workflows_dir)
        browser_config = BrowserConfig(cdp_url=CDP_URL, headless=self.headless)

        # 3. Build agent factory and runners
        agent_factory = DefaultBrowserAgentFactory(
            llm=playmaker_llm,
            use_vision=self.use_vision,
            max_failures=self.max_failures,
            retry_delay=self.retry_delay,
        )

        fallback_runner = LlmWorkflowRunner(
            agent_factory=agent_factory,
            repository=workflow_repo,
            browser_config=browser_config,
        )

        replay_runner = PlaywrightReplayRunner(
            repository=workflow_repo,
            llm=analyst_llm,
            browser_config=browser_config,
        )

        runner = SelfHealingRunner(
            replay_runner=replay_runner,
            fallback_runner=fallback_runner,
            repository=workflow_repo,
        )

        browser_manager: BrowserManager = CloakBrowserManager()
        cdp_checker: CdpChecker = HttpCdpConnectionChecker(CDP_URL)
        run_autopass_use_case: RunAutopassUseCase = RunAutopassUseCase(
            browser_manager=browser_manager,
            cdp_checker=cdp_checker,
            workflow_runner=runner,
        )

        async def run_use_case() -> str:
            prepared = await self.prepared_run()
            return await run_autopass_use_case.run(
                task_prompt=self.task,
                profile_path=profile_path,
                headless=self.headless,
                cdp_port=CDP_PORT,
                listener=QuickProgressListener(),
                run_name=prepared.run_name,
                run_id=prepared.run_id,
            )

        prepared = await self.prepared_run()
        schedule_value: str | None = prepared.parameters.get("schedule", None)
        raw_output = await self.orchestrator.execute(
            self.task, prepared, run_use_case, schedule_value
        )

        autopass_output: AutopassRunOutput = AutopassRunOutput(
            task_prompt=self.task,
            final_message=str(raw_output),
        )

        return RunResult(
            run_id=prepared.run_id,
            status=RunStatus.COMPLETED,
            data=autopass_output,
        )


if __name__ == "__main__":
    AutopassSession.cli("autopass")
