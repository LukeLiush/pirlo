import os
from pathlib import Path
from typing import Any

from pirlo.core.instructions import AutopassInstructions, Instruction
from pirlo.core.ports.pitch import LinkParameter, Parameter
from pirlo.core.services.profile_manager import ProfileManager
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.playbooks.autopass.adapters.browser_manager import CloakBrowserManager
from pirlo.playbooks.autopass.adapters.cdp_checker import HttpCdpConnectionChecker
from pirlo.playbooks.autopass.adapters.workflow_executor import (
    SelfHealingWorkflowExecutor,
)
from pirlo.playbooks.autopass.core.ports import ProgressListener
from pirlo.playbooks.autopass.core.use_cases import RunAutopassUseCase

PIRLO_WORKSPACE = Path(os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")).expanduser()


CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


class AutopassSession(TerminalPitch, ProgressListener):
    """Run self-healing browser automation workflows."""

    default_config_path = PIRLO_WORKSPACE / "autopass" / "last_params.json"

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

    def yellow_card(self, message: str | Instruction, detail: str | None = None):
        if isinstance(message, Instruction):
            super().yellow_card(message.message, detail=message.detail)
        else:
            super().yellow_card(message, detail=detail)

    # Implement ProgressListener port
    def status_context(self, message: str) -> Any:
        return self.status(message)

    def show_warning(self, message: Any, detail: str | None = None) -> None:
        self.yellow_card(message, detail=detail)

    def show_goal(self, message: str, detail: str | None = None) -> None:
        self.goal(message, detail=detail)

    def show_red_card(self, message: str, detail: str | None = None) -> None:
        self.red_card(message, detail=detail)

    async def play(self):
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
            return

        if ProfileManager.is_expired(self.profile):
            meta = ProfileManager.load_profile_metadata(self.profile)
            exp_date = meta.expires_at if meta else "N/A"
            urls_str = (
                " ".join(meta.authenticated_urls)
                if (meta and meta.authenticated_urls)
                else "<target_urls>"
            )
            instruction = AutopassInstructions.PROFILE_EXPIRED.format(
                profile=self.profile, expires_at=exp_date, authenticated_urls=urls_str
            )
            self.yellow_card(instruction)
            return

        profile_path: Path = ProfileManager.resolve_profile_path(self.profile)

        if self.task is None:
            self.yellow_card(AutopassInstructions.TASK_REQUIRED)
            return

        if self.playmaker is None or self.analyst is None:
            self.yellow_card(
                "Error: Playmaker and Analyst links are required.\n"
                "Please specify --playmaker and --analyst.\n"
                "Run 'pirlo link list' to see available links, or 'pirlo link create' to register a new one."
            )
            return

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
                    f"{self.playmaker.name} ({self.playmaker.provider})",
                ],
                ["Playmaker Model", self.playmaker.model],
                ["Playmaker Base URL", pm_base_url or "N/A"],
                [
                    "Analyst Link (Provider)",
                    f"{self.analyst.name} ({self.analyst.provider})",
                ],
                ["Analyst Model", self.analyst.model],
                ["Analyst Base URL", an_base_url or "N/A"],
                ["Vision Enabled", str(self.use_vision)],
                ["Max Failures / Delay", f"{self.max_failures} / {self.retry_delay}s"],
            ],
        )

        # Instantiate adapters
        browser_manager = CloakBrowserManager()
        cdp_checker = HttpCdpConnectionChecker(CDP_URL)
        workflow_executor = SelfHealingWorkflowExecutor(CDP_URL, self._parsed_options)

        # Instantiate and run use case
        use_case = RunAutopassUseCase(
            browser_manager=browser_manager,
            cdp_checker=cdp_checker,
            workflow_executor=workflow_executor,
        )

        await use_case.run(
            task_prompt=self.task,
            profile_path=profile_path,
            headless=self.headless,
            cdp_port=CDP_PORT,
            listener=self,
        )


if __name__ == "__main__":
    AutopassSession.cli()
