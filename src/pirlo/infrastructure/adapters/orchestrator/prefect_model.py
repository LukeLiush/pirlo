# src/pirlo/infrastructure/adapters/orchestrator/prefect_model.py
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput


@dataclass(frozen=True)
class PrefectWorkflow:
    """Compiled Prefect execution model holding the generated @flow callable and source IR metadata."""

    name: str
    flow: Callable[..., Awaitable[PlayOutput | None]]
    blueprint: PlayBlueprint

    async def __call__(self, **kwargs: Any) -> PlayOutput | None:
        """Enables direct invocation of the underlying Prefect flow."""
        return await self.flow(**kwargs)
