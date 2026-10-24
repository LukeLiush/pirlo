# src/pirlo/core/models/command.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Command:
    """An external program invocation: an argv tuple, never a shell string."""

    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("Command argv must not be empty.")


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a finished Command, whether it succeeded, failed, or timed out."""

    command: Command
    exit_code: int
    duration_s: float
    output_tail: str
    log_path: Path
    timed_out: bool = False
