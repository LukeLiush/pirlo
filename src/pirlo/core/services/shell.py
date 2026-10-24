# src/pirlo/core/services/shell.py
from __future__ import annotations

import logging
import os
import shlex
from collections.abc import Collection, Mapping
from pathlib import Path

from pirlo.core.models.command import Command, CommandResult
from pirlo.core.ports.command_runner import CommandRunner


class CommandFailed(Exception):
    """Raised when a command exits with a code outside ok_codes or times out."""

    def __init__(self, result: CommandResult) -> None:
        outcome = (
            f"timed out after {result.command.timeout_s}s"
            if result.timed_out
            else f"exited {result.exit_code}"
        )
        super().__init__(
            f"`{shlex.join(result.command.argv)}` {outcome} (full log: {result.log_path})"
        )
        self.result: CommandResult = result


class Shell:
    """Runs commands for a play: logs each invocation, streams its output into the
    play's logger as it arrives, and applies the exit-code policy."""

    def __init__(self, runner: CommandRunner, logger: logging.Logger) -> None:
        self._runner: CommandRunner = runner
        self._logger: logging.Logger = logger

    async def run(
        self,
        *argv: str | os.PathLike[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        ok_codes: Collection[int] = (0,),
        timeout_s: float | None = None,
    ) -> CommandResult:
        """Runs argv to completion and returns its result.

        Raises CommandFailed if it times out or exits with a code outside ok_codes.
        """
        command = Command(
            argv=tuple(os.fspath(arg) for arg in argv),
            cwd=cwd,
            env=dict(env or {}),
            timeout_s=timeout_s,
        )
        self._logger.info("$ %s", shlex.join(command.argv))
        result = await self._runner.run(
            command, on_line=lambda line: self._logger.info("%s", line)
        )
        self._logger.info(
            "exit %d in %.1fs%s",
            result.exit_code,
            result.duration_s,
            " (timed out)" if result.timed_out else "",
        )
        if result.timed_out or result.exit_code not in ok_codes:
            raise CommandFailed(result)
        return result
