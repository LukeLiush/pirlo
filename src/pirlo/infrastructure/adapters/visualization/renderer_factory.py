# src/pirlo/infrastructure/adapters/visualization/renderer_factory.py
from __future__ import annotations

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer


class BlueprintRendererFactory:
    """Factory creating configured BlueprintRenderer instances."""

    @staticmethod
    def get_renderer(name: str = "auto") -> BlueprintRenderer:
        from pirlo.infrastructure.adapters.visualization.fallback_renderer import (
            FallbackBlueprintRenderer,
        )
        from pirlo.infrastructure.adapters.visualization.grandalf_renderer import (
            GrandalfBlueprintRenderer,
        )
        from pirlo.infrastructure.adapters.visualization.simple_renderer import (
            SimpleBlueprintRenderer,
        )

        if name == "auto":
            return FallbackBlueprintRenderer(
                primary=GrandalfBlueprintRenderer(),
                fallback=SimpleBlueprintRenderer(),
            )
        if name == "grandalf":
            return GrandalfBlueprintRenderer()
        if name == "simple":
            return SimpleBlueprintRenderer()

        raise ValueError(f"Unknown blueprint renderer '{name}'.")
