from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async

from pirlo.playbooks.autopass.core.ports import BrowserManager


class CloakBrowserManager(BrowserManager):
    """Adapter implementing BrowserManager using CloakBrowser."""

    def __init__(self):
        self._ctx = None

    async def launch(self, profile_path: Path, headless: bool, cdp_port: int) -> Any:
        self._ctx = await launch_persistent_context_async(
            str(profile_path),
            headless=headless,
            humanize=False,
            args=[f"--remote-debugging-port={cdp_port}"],
        )
        return self._ctx

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
            self._ctx = None
