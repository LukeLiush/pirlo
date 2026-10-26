from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class LocalServerError(Exception):
    """Raised when a local orchestrator server cannot be started."""


@dataclass(frozen=True)
class LocalServerStatus:
    """A running local orchestrator server, as recorded by whoever started it."""

    pid: int
    port: int
    api_url: str
    started_at: str
    log_path: Path


class LocalServer(ABC):
    """Port for starting, inspecting and stopping a local orchestrator server."""

    @abstractmethod
    def start(self, preferred_port: int) -> LocalServerStatus:
        """Starts the server, or returns the one already running."""

    @abstractmethod
    def status(self) -> LocalServerStatus | None:
        """Returns the running server if it is alive and answering, else None."""

    @abstractmethod
    def stop(self) -> bool:
        """Stops the recorded server. Returns False when none was recorded."""
