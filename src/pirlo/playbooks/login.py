import asyncio
from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async

from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.infrastructure.services.profile_manager import ProfileManager


class LoginSession(TerminalPitch):
    """Launch a browser to authenticate and save persistent cookies."""

    profile = Parameter(
        str,
        default="default",
        help="Name or path of the browser profile to authenticate and save",
    )

    ttl_days = Parameter(
        int,
        default=7,
        help="Session expiration TTL in days (default: 7)",
    )

    urls = Parameter(
        list[str],
        default=[],
        help="List of target website URLs to open for manual authentication",
    )

    urls_file = Parameter(
        Path,
        help="Path to a text file containing a list of target URLs (one per line)",
    )

    async def on_play(self) -> RunResult[Any]:
        # 1. Header (Banner)
        self.header(
            "Pirlo Login Manager",
            subtitle=f"Manage persistent session cookies for profile '{self.profile}'",
        )

        target_urls: list[str] = self.urls.copy() if self.urls else []
        if self.urls_file:
            if self.urls_file.exists():
                with open(self.urls_file, "r") as f:  # noqa: ASYNC230
                    target_urls.extend(
                        line.strip() for line in f.read().splitlines() if line.strip()
                    )
            else:
                instruction = f"The specified file '{self.urls_file}' does not exist."
                self.yellow_card(
                    "URLs file not found",
                    detail=instruction,
                )
                return RunResult(
                    run_id=self._prepared_run.run_id,
                    status=RunStatus.FAILED,
                    error=instruction,
                )

        # Filter out empty strings
        target_urls = [url.strip() for url in target_urls if url.strip()]

        if not target_urls:
            no_urls_msg = (
                "Please provide at least one target URL. You can:\n"
                "  1. Pass URLs directly using [bold]--urls[/bold] (e.g., --urls https://github.com)\n"
                "  2. Pass a text file with URLs using [bold]--urls-file[/bold] (e.g., --urls-file urls.txt)\n\n"
                "Example:\n"
                "  [cyan]pirlo login --profile work --urls https://github.com https://google.com[/cyan]"
            )
            self.yellow_card(
                "No URLs to open",
                detail=no_urls_msg,
            )
            return RunResult(
                run_id=self._prepared_run.run_id,
                status=RunStatus.FAILED,
                error=no_urls_msg,
            )

        # 2. Status (Loading spinner)
        profile_path = ProfileManager.resolve_profile_path(self.profile)
        with self.status(f"Launching browser session for profile '{self.profile}'..."):
            ctx = await launch_persistent_context_async(
                str(profile_path),
                headless=False,
                humanize=True,
            )
            # 3. Open the target URLs in parallel tabs
            initial_pages = ctx.pages
            tasks = []

            try:
                for i, url in enumerate(target_urls):
                    if i < len(initial_pages):
                        page = initial_pages[i]
                    else:
                        page = await ctx.new_page()
                    tasks.append(page.goto(url, wait_until="domcontentloaded"))

                await asyncio.gather(*tasks)

                # 4. Lineup (Table of targets dynamically built from target_urls)
                rows = []
                for url in target_urls:
                    domain = url.split("://")[-1].split("/")[0].replace("www.", "")
                    rows.append([domain.capitalize(), url, "Manual Login"])

                self.lineup(
                    "Target Portals",
                    columns=["Portal", "URL", "Required Action"],
                    rows=rows,
                )

                # 5. VAR Check (Interactive prompt)
                await self.var_check(
                    "Press [ENTER] once you are successfully logged in to save and exit"
                )

                # Save metadata
                metadata = ProfileManager.save_profile_metadata(
                    profile_input=self.profile,
                    urls=target_urls,
                    ttl_days=self.ttl_days,
                )

                # 6. Goal! (Success box)
                self.goal(
                    "Session Saved Successfully!",
                    detail=(
                        f"Browser cookies saved to: {profile_path.resolve()}\n"
                        f"Profile Name: {metadata.name}\n"
                        f"Expires At: {metadata.expires_at} (TTL: {self.ttl_days} days)"
                    ),
                )
                return RunResult(
                    run_id=self._prepared_run.run_id,
                    status=RunStatus.COMPLETED,
                    data={"profile": self.profile, "urls": target_urls},
                )
            finally:
                await ctx.close()


if __name__ == "__main__":
    LoginSession.cli("login")

