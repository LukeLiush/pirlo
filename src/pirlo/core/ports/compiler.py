# src/pirlo/core/ports/compiler.py
from __future__ import annotations

from abc import ABC, abstractmethod

from pirlo.core.models.blueprint import PlayBlueprint


class BlueprintCompiler[WorkflowT](ABC):
    """Abstract Port for compiling a PlayBlueprint IR into an engine-specific workflow model."""

    @abstractmethod
    def compile(self, blueprint: PlayBlueprint) -> WorkflowT:
        """Translates the PlayBlueprint IR into the target engine workflow model."""
        raise NotImplementedError
