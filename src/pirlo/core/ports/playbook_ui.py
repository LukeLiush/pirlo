"""Backward compatibility module forwarding to play_ui."""

from __future__ import annotations

from pirlo.core.ports.play_ui import PlaybookUI, PlayUI

__all__ = ["PlayUI", "PlaybookUI"]
