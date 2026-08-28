from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async

from pirlo.playbooks.autopass.core.ports import BrowserManager as BaseBrowserManager


class CloakBrowserManager(BaseBrowserManager):
    """Unified manager for persistent browser process and Playwright page lifecycles."""

    def __init__(
        self, profile_path: Path, headless: bool = True, cdp_port: int = 9222
    ) -> None:
        self.profile_path = profile_path
        self.headless = headless
        self.cdp_port = cdp_port
        self._ctx: Any = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[CloakBrowserManager]:
        """Launches the persistent CloakBrowser context on enter, and closes it on exit."""
        self._ctx = await launch_persistent_context_async(
            str(self.profile_path),
            headless=self.headless,
            humanize=False,
            args=[f"--remote-debugging-port={self.cdp_port}"],
        )
        try:
            yield self
        finally:
            if self._ctx:
                await self._ctx.close()
                self._ctx = None

    @asynccontextmanager
    async def new_page(self) -> AsyncIterator[Any]:
        """Spawns an isolated Playwright Page and closes it on exit."""
        if not self._ctx:
            raise RuntimeError(
                "Browser session is not active. Call inside 'async with browser_manager.session()'."
            )
        page = await self._ctx.new_page()
        try:
            yield page
        finally:
            await page.close()
