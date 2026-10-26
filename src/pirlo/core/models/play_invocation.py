# src/pirlo/core/models/play_invocation.py
"""Value object for the CLI arguments passed to a play."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayInvocation:
    """CLI arguments for a play, after its command name."""

    play_args: list[str]

    @property
    def playbook_args(self) -> list[str]:
        return self.play_args

    @classmethod
    def from_raw(cls, raw_arguments: list[str]) -> PlayInvocation:
        return cls(play_args=list(raw_arguments))
