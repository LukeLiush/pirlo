"""Backward compatibility module forwarding to terminal_play_ui."""

from __future__ import annotations

from pirlo.infrastructure.adapters.cli.terminal_play_ui import (
    TerminalPlaybookUI,
    TerminalPlayUI,
)

__all__ = ["TerminalPlayUI", "TerminalPlaybookUI"]
