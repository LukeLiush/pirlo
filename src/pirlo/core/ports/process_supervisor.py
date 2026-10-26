from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessSpec:
    """One long-running command for a supervisor, with its complete environment."""

    name: str
    command: list[str]
    env: dict[str, str]


class ProcessSupervisor(ABC):
    """Port for running a set of processes in the foreground as one unit."""

    @abstractmethod
    def run(self, processes: list[ProcessSpec]) -> int:
        """Runs every process until one exits or the supervisor is told to stop.

        Stopping (Ctrl-C, SIGTERM, or the terminal closing) ends all of them.
        Returns an exit code for the whole set.
        """
