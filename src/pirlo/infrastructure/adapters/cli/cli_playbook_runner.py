# src/pirlo/infrastructure/adapters/cli/cli_playbook_runner.py
"""Backward-compatibility module forwarding CliPlaybookRunner to CliPlayRunner."""

from __future__ import annotations

from pirlo.infrastructure.adapters.cli.cli_play_runner import (
    CliPlayRunner,
    extract_raw_arguments_excluding_command,
)

CliPlaybookRunner = CliPlayRunner

__all__ = [
    "CliPlayRunner",
    "CliPlaybookRunner",
    "extract_raw_arguments_excluding_command",
]
