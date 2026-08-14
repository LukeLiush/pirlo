from abc import ABC, abstractmethod

from pirlo.core.models.plan import DecomposerPlan


class PlanRepository(ABC):
    """Abstract interface for persisting and loading Decomposer Plans."""

    @abstractmethod
    def exists(self, plan_id: str) -> bool:
        """Check if a plan with the given plan_id exists in the repository."""

    @abstractmethod
    def load(self, plan_id: str) -> DecomposerPlan:
        """Load a plan by its plan_id. Raises FileNotFoundError if missing."""

    @abstractmethod
    def save(self, plan: DecomposerPlan) -> None:
        """Save a DecomposerPlan to the repository."""
