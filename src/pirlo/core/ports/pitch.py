from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.models.run_result import RunResult


class Pitch(ABC):
    """Pure Abstract Port representing the presentation canvas & lifecycle contract."""

    @abstractmethod
    async def prepared_run(self) -> Any:
        """Return the prepared run instance."""

    @abstractmethod
    async def on_play(self, *args: Any, **kwargs: Any) -> RunResult[Any]:
        """Core playbook execution logic implemented by subclasses."""

    @abstractmethod
    async def play(self) -> RunResult[Any]:
        """Framework template method managing execution lifecycle."""

    @abstractmethod
    def header(self, title: str, subtitle: str | None = None) -> None:
        """Draw a banner/header."""

    @abstractmethod
    def status(self, message: str) -> Any:
        """Context manager for loading status (spinner)."""

    @abstractmethod
    def lineup(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        """Draw starting lineup table."""

    @abstractmethod
    async def var_check(self, message: str) -> None:
        """VAR Check: Halts play to pause and wait for the user to press Enter."""

    @abstractmethod
    def goal(self, message: str, detail: str | None = None) -> None:
        """Draw success panel (Scoring a goal!)."""

    @abstractmethod
    def red_card(self, message: str, detail: str | None = None) -> None:
        """Draw error panel (Red Card!)."""

    @abstractmethod
    def yellow_card(self, message: str, detail: str | None = None) -> None:
        """Draw warning panel (Warning flag)."""
