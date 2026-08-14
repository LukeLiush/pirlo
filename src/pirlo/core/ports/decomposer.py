from abc import ABC, abstractmethod

from pirlo.core.models.plan import DecomposerPlan


class DecomposerPort(ABC):
    """Abstract port for decomposing multi-target requests into atomic subtasks."""

    @abstractmethod
    async def decompose(self, user_prompt: str) -> DecomposerPlan:
        """Decompose a high-level user prompt into a DecomposerPlan."""
