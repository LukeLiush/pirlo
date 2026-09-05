# src/pirlo/core/models/play_invocation.py
"""Value object for CLI arguments split at the orchestrator delimiter."""

from __future__ import annotations

from dataclasses import dataclass


def ensure_canonical_orchestrator_delimiter(
    raw_arguments: list[str], default_orchestrator_name: str = "prefect"
) -> list[str]:
    """Ensures '-- <default_orchestrator_name>' is attached to raw CLI arguments if '--' is omitted."""
    if "--" not in raw_arguments:
        return raw_arguments + ["--", default_orchestrator_name]
    return raw_arguments


@dataclass(frozen=True)
class PlayInvocation:
    """CLI arguments split at the ``--`` orchestrator delimiter."""

    play_args: list[str]
    orchestrator_args: list[str]

    @property
    def playbook_args(self) -> list[str]:
        return self.play_args

    @classmethod
    def from_raw(
        cls,
        raw_arguments: list[str],
        *,
        default_orchestrator_name: str = "prefect",
    ) -> PlayInvocation:
        canonical = ensure_canonical_orchestrator_delimiter(
            raw_arguments, default_orchestrator_name=default_orchestrator_name
        )
        split_index = canonical.index("--")
        return cls(
            play_args=canonical[:split_index],
            orchestrator_args=canonical[split_index + 1 :],
        )


# Backward-compatibility alias
PlaybookInvocation = PlayInvocation
