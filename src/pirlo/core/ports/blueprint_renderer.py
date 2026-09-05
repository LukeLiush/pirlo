# src/pirlo/core/ports/blueprint_renderer.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint


class BlueprintRenderer(ABC):
    """Port for rendering a PlayBlueprint into a human-readable visual representation."""

    @abstractmethod
    def render(self, blueprint: PlayBlueprint) -> str:
        """Renders the PlayBlueprint into a formatted string (e.g. ASCII or Unicode)."""
        raise NotImplementedError
