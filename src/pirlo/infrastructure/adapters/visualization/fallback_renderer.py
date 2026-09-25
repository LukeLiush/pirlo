# src/pirlo/infrastructure/adapters/visualization/fallback_renderer.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint

logger = logging.getLogger(__name__)


class FallbackBlueprintRenderer(BlueprintRenderer):
    """Tries a primary renderer, degrading to a fallback when it cannot render."""

    def __init__(self, primary: BlueprintRenderer, fallback: BlueprintRenderer) -> None:
        self.primary = primary
        self.fallback = fallback

    def render(self, blueprint: PlayBlueprint) -> str:
        try:
            return self.primary.render(blueprint)
        except Exception as err:  # noqa: BLE001
            logger.warning(
                "%s could not render blueprint '%s' (%s); falling back to %s",
                type(self.primary).__name__,
                blueprint.name,
                err,
                type(self.fallback).__name__,
            )
            return self.fallback.render(blueprint)
