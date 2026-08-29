from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any


class PitchUI(ABC):
    """Pure Abstract Port representing presentation rendering and user interaction."""

    @abstractmethod
    def header(self, title: str, subtitle: str | None = None) -> None:
        """Draw a banner/header."""

    @abstractmethod
    def status(self, message: str) -> AbstractContextManager[Any]:
        """Context manager for loading/pending status indicator."""

    @abstractmethod
    def lineup(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        """Draw starting lineup table/data structure."""

    @abstractmethod
    def commentary(self, message: str, detail: str | None = None) -> None:
        """Draw standard informational log message / live match commentary."""

    @abstractmethod
    async def var_check(self, message: str) -> None:
        """Halts play to pause and wait for user confirmation."""

    @abstractmethod
    def goal(self, message: str, detail: str | None = None) -> None:
        """Draw success panel/message (Scoring a goal!)."""

    @abstractmethod
    def red_card(self, message: str, detail: str | None = None) -> None:
        """Draw error panel/message (Red Card!)."""

    @abstractmethod
    def yellow_card(self, message: Any, detail: str | None = None) -> None:
        """Draw warning panel/message (Yellow Card!)."""
