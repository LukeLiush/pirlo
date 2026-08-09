from pathlib import Path

from pirlo.core.instructions import AutopassInstructions
from pirlo.core.ports.orchestrator import AutopassExecutionOptions
from pirlo.core.ports.pitch import LinkParameter, Parameter
from pirlo.core.services.profile_manager import ProfileManager
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    run_self_healing_worker_task,
)

CDP_PORT = 9222

CDP_URL = f"http://localhost:{CDP_PORT}"


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

    orchestrator = Parameter(
        str,
        default="prefect",
        help="Orchestrator backend engine name (default: 'prefect')",
        env_name="ORCHESTRATOR",
    )
    server_url = Parameter(
        str,
        default=None,
        help="Orchestrator server API URL override",
        env_name="SERVER_URL",
    )
    work_pool = Parameter(
        str,
        default=None,
        help="Orchestrator work pool override",
        env_name="WORK_POOL",
    )

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
                ["Orchestrator Backend", getattr(self, "orchestrator", "prefect")],
                ["Schedule", self.schedule or "None (Immediate)"],
            ],
        )

        options = AutopassExecutionOptions(
            playmaker=self.playmaker,
            analyst=self.analyst,
            use_vision=self.use_vision,
            max_failures=self.max_failures,
            retry_delay=self.retry_delay,
            generate_gif=getattr(self, "generate_gif", False),
            cron=self.schedule,
        )

        from pirlo.infrastructure.adapters.orchestrator.factory import (
            OrchestratorFactory,
        )

        orchestrator = OrchestratorFactory.create(
            name=getattr(self, "orchestrator", "prefect"),
            server_url=getattr(self, "server_url", None),
            work_pool=getattr(self, "work_pool", None),
        )
        await orchestrator.execute(
            self,
            worker_fn=lambda: run_self_healing_worker_task(
                task_prompt=self.task,
                profile_path=profile_path,
                headless=self.headless,
                cdp_port=CDP_PORT,
                options=options,
                run_dir=self.run_dir,
            ),
        )


if __name__ == "__main__":
    AutopassSession.cli()
