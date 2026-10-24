# src/pirlo/core/utils/ansi.py
from __future__ import annotations

import re

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\b\[\d+m")


def strip_ansi(text: str) -> str:
    """Removes ANSI color and cursor escape sequences from text."""
    return ANSI_PATTERN.sub("", text)
