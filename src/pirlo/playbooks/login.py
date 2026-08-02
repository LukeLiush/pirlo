import asyncio
from pathlib import Path

from cloakbrowser import launch_persistent_context_async

from pirlo.core.ports.pitch import Parameter
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class LoginSession(TerminalPitch):
    """Launch a browser to authenticate and save persistent cookies."""

    links = Parameter(list[str], default=[], help="List of target URLs")

    link_path = Parameter(Path, help="Path to a file containing a list of URLs")

    async def play(self):
        # 1. Header (Banner)
        self.header(
            "Pirlo Login Manager",
            subtitle="Manage persistent user session cookies",
        )

        the_links: list[str] = self.links.copy() if self.links else []
        if self.link_path:
            if self.link_path.exists():
                with open(self.link_path, "r") as f:  # noqa: ASYNC230
                    the_links.extend(
                        line.strip() for line in f.read().splitlines() if line.strip()
                    )
            else:
                self.yellow_card(
                    "Link path not found",
                    detail=f"The specified file '{self.link_path}' does not exist.",
                )

        # Filter out empty strings
        the_links = [link.strip() for link in the_links if link.strip()]

        if not the_links:
            self.yellow_card(
                "No URLs to open",
                detail=(
                    "Please provide at least one target URL. You can:\n"
                    "  1. Pass URLs directly using [bold]--links[/bold] (e.g., --links https://github.com)\n"
                    "  2. Pass a text file with URLs using [bold]--link-path[/bold] (e.g., --link-path urls.txt)\n\n"
                    "Example:\n"
                    "  [cyan]uv run pirlo login --links https://github.com https://google.com[/cyan]"
                ),
            )
            return

        # 2. Status (Loading spinner)
        with self.status("Launching browser session..."):
            profile_path = Path("~/.pirlo-pitch/login-profile")
            ctx = await launch_persistent_context_async(
                str(profile_path),
                headless=False,
                humanize=True,
            )
            # 3. Open the target URLs in parallel tabs
            initial_pages = ctx.pages
            tasks = []

            try:
                for i, url in enumerate(the_links):
                    if i < len(initial_pages):
                        page = initial_pages[i]
                    else:
                        page = await ctx.new_page()
                    tasks.append(page.goto(url, wait_until="domcontentloaded"))

                await asyncio.gather(*tasks)

                # 4. Lineup (Table of targets dynamically built from self.links)
                rows = []
                for url in the_links:
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
                # 6. Goal! (Success box)
                self.goal(
                    "Session Saved Successfully!",
                    detail=f"Browser cookies saved to: {profile_path.resolve()}",
                )
            finally:
                await ctx.close()


if __name__ == "__main__":
    LoginSession.cli()
