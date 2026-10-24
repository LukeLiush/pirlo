# tests/command_runner_stub.py
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pirlo.core.models.command import Command, CommandResult
from pirlo.core.ports.command_runner import CommandRunner


@dataclass(frozen=True)
class _CannedResponse:
    exit_code: int
    output: str
    timed_out: bool


class StubCommandRunner(CommandRunner):
    """Test double: replays canned output per argv and records every command it ran.

    Unknown commands raise LookupError so a test never silently passes on a typo.
    """

    def __init__(self) -> None:
        self.calls: list[Command] = []
        self._responses: dict[tuple[str, ...], _CannedResponse] = {}

    def respond(
        self,
        *argv: str,
        exit_code: int = 0,
        output: str = "",
        timed_out: bool = False,
    ) -> StubCommandRunner:
        self._responses[argv] = _CannedResponse(exit_code, output, timed_out)
        return self

    async def run(
        self, command: Command, on_line: Callable[[str], None]
    ) -> CommandResult:
        self.calls.append(command)
        response = self._responses.get(command.argv)
        if response is None:
            raise LookupError(f"StubCommandRunner has no response for {command.argv}")
        lines = response.output.splitlines()
        for line in lines:
            on_line(line)
        return CommandResult(
            command=command,
            exit_code=response.exit_code,
            duration_s=0.0,
            output_tail="\n".join(lines),
            log_path=Path(os.devnull),
            timed_out=response.timed_out,
        )
