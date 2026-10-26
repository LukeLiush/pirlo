from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class WorkerFleetError(Exception):
    """Raised when workers for the work pool cannot be started."""


@dataclass(frozen=True)
class WorkerInfo:
    """One running worker, as recorded by whoever started it."""

    name: str
    pid: int
    pool: str
    limit: int
    started_at: str
    log_path: Path


class WorkerFleet(ABC):
    """Port for the workers that execute runs submitted to a work pool."""

    @abstractmethod
    def start(self, api_url: str) -> list[WorkerInfo]:
        """Starts workers against the server, or returns the ones already running."""

    @abstractmethod
    def status(self) -> list[WorkerInfo]:
        """Returns the workers whose processes are alive."""

    @abstractmethod
    def stop(self) -> int:
        """Stops the recorded workers and returns how many there were."""
