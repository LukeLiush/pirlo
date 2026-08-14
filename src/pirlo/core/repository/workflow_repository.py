from abc import ABC, abstractmethod

from pirlo.core.models import Workflow


class WorkflowRepository(ABC):
    """Abstract port for persisting and loading Workflow domain objects."""

    @abstractmethod
    def exists(self, workflow_id: str) -> bool:
        """Checks if a workflow cache exists."""

    @abstractmethod
    def load(self, workflow_id: str) -> Workflow:
        """Loads a workflow from storage."""

    @abstractmethod
    def save(self, workflow: Workflow) -> None:
        """Persists a workflow to storage."""
