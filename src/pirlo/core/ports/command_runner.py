# src/pirlo/core/ports/command_runner.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from pirlo.core.models.command import Command, CommandResult


class CommandRunner(ABC):
    """Abstract Port for executing external commands with live line-by-line output."""

    @abstractmethod
    async def run(
        self, command: Command, on_line: Callable[[str], None]
    ) -> CommandResult:
        """Runs the command to completion, calling on_line for each output line as it arrives.

        Always returns a result; callers decide which exit codes count as failure.
        """
        raise NotImplementedError
