"""Backward compatibility module forwarding to play_invocation."""

from __future__ import annotations

from pirlo.core.models.play_invocation import (
    PlaybookInvocation,
    PlayInvocation,
    ensure_canonical_orchestrator_delimiter,
)

__all__ = [
    "PlayInvocation",
    "PlaybookInvocation",
    "ensure_canonical_orchestrator_delimiter",
]
