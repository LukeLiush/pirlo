import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from pirlo.core.instructions import AutopassInstructions, Instruction
from pirlo.core.models.link import ApiKeyLink, LlmLink
from pirlo.core.ports.pitch import LinkParameter, Parameter
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.playground.autopass.adapters.browser_manager import CloakBrowserManager
from pirlo.playground.autopass.adapters.cdp_checker import HttpCdpConnectionChecker
from pirlo.playground.autopass.adapters.workflow_executor import SelfHealingWorkflowExecutor
from pirlo.playground.autopass.core.ports import ProgressListener
from pirlo.playground.autopass.core.use_cases import RunAutopassUseCase

PIRLO_WORKSPACE = Path(os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")).expanduser()


def get_profile_path(profile_name: str = "login-profile") -> Path:
    PIRLO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    return PIRLO_WORKSPACE / profile_name


CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


class AutopassSession(TerminalPitch, ProgressListener):
    """Run self-healing browser automation workflows."""
    default_config_path = PIRLO_WORKSPACE / "autopass" / "autopass.json"

    headless = Parameter(
        bool, default=False, help="Run browser in headless mode", env_name="HEADLESS"
    )
    task = Parameter(
        str, default=None, help="Task prompt to execute autonomously", env_name="TASK"
    )
    playmaker: LlmLink = LinkParameter(
        help="Link name for Playmaker (decision brain)", env_name="PLAYMAKER"
    )
    analyst: LlmLink = LinkParameter(
        help="Link name for Analyst (DOM summary / selector healer)", env_name="ANALYST"
    )
    use_vision = Parameter(
        bool, default=False, help="Enable vision for the Agent", env_name="USE_VISION"
    )
    max_failures = Parameter(
        int, default=5, help="Maximum failure attempts before stopping", env_name="MAX_FAILURES"
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
    def status_context(self, message: str) -> AbstractContextManager[None]:
        return self.status(message)

    def show_warning(self, message: Any, detail: str = None) -> None:
        self.yellow_card(message, detail=detail)

    def show_goal(self, message: str, detail: str = None) -> None:
        self.goal(message, detail=detail)

    def show_red_card(self, message: str, detail: str = None) -> None:
        self.red_card(message, detail=detail)

    async def play(self):
        self.header(
            "Autopass Workflow Pitch",
            subtitle="Autonomous Browser Automation",
        )

        profile_path: Path = get_profile_path()
        if not profile_path.exists():
            self.yellow_card(AutopassInstructions.PROFILE_MISSING)
            profile_path.mkdir(parents=True, exist_ok=True)

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
        pm_base_url = self.playmaker.base_url if isinstance(self.playmaker, ApiKeyLink) else "N/A"
        an_base_url = self.analyst.base_url if isinstance(self.analyst, ApiKeyLink) else "N/A"

        self.lineup(
            "Active Run Configuration",
            columns=["Setting", "Value"],
            rows=[
                ["Profile Path", str(profile_path.resolve())],
                ["Headless", str(self.headless)],
                ["Task", self.task],
                ["Playmaker Link (Provider)", f"{self.playmaker.name} ({self.playmaker.provider})"],
                ["Playmaker Model", self.playmaker.model],
                ["Playmaker Base URL", pm_base_url or "N/A"],
                ["Analyst Link (Provider)", f"{self.analyst.name} ({self.analyst.provider})"],
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

        try:
            await use_case.run(
                task_prompt=self.task,
                profile_path=profile_path,
                headless=self.headless,
                cdp_port=CDP_PORT,
                listener=self,
            )
        except Exception as e:
            # We already notify the red_card in the use case via listener
            raise e


if __name__ == "__main__":
    AutopassSession.cli()
