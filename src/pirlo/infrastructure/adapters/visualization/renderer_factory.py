# src/pirlo/infrastructure/adapters/visualization/renderer_factory.py
from __future__ import annotations

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer


class BlueprintRendererFactory:
    """Factory creating configured BlueprintRenderer instances."""

    @staticmethod
    def get_renderer(name: str = "grandalf") -> BlueprintRenderer:
        if name == "grandalf":
            from pirlo.infrastructure.adapters.visualization.grandalf_renderer import (
                GrandalfBlueprintRenderer,
            )

            return GrandalfBlueprintRenderer()

        raise ValueError(f"Unknown blueprint renderer '{name}'.")
