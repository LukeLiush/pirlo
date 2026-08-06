from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


class BrowserManager(ABC):
    """Port for browser session lifecycle operations."""

    @abstractmethod
    async def launch(self, profile_path: Path, headless: bool, cdp_port: int) -> Any:
        """Launch a browser session and return the browser/context instance."""

    @abstractmethod
    async def close(self) -> None:
        """Close the active browser session and clean up resources."""


class CdpChecker(ABC):
    """Port for checking CDP endpoint availability."""

    @abstractmethod
    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        """Block until the CDP endpoint becomes responsive, or timeout expires."""


class ProgressListener(ABC):
    """Port for presenting status updates and notifications to the user."""

    @abstractmethod
    def status_context(self, message: str) -> AbstractContextManager[None]:
        """A context manager displaying a pending/loading status message."""

    @abstractmethod
    def show_warning(self, message: Any, detail: str | None = None) -> None:
        """Display a warning to the user."""

    @abstractmethod
    def show_goal(self, message: str, detail: str | None = None) -> None:
        """Display a success/completion message."""

    @abstractmethod
    def show_red_card(self, message: str, detail: str | None = None) -> None:
        """Display an error/failure message."""
