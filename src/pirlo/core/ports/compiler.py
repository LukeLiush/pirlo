# src/pirlo/core/ports/compiler.py
from __future__ import annotations

from abc import ABC, abstractmethod

from pirlo.core.models.blueprint import PlaybookBlueprint, PlaybookOutput


class BlueprintCompiler[TargetT](ABC):
    """Abstract Port for compiling a PlaybookBlueprint IR into an orchestrator workflow."""

    @classmethod
    @abstractmethod
    def compile(cls, blueprint: PlaybookBlueprint) -> TargetT:
        """Translates the PlaybookBlueprint IR into the target engine representation."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def run_ephemeral(cls, blueprint: PlaybookBlueprint) -> PlaybookOutput | None:
        """Executes the PlaybookBlueprint in local ephemeral mode."""
        raise NotImplementedError
