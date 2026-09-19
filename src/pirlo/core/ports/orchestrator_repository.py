from __future__ import annotations

from abc import ABC, abstractmethod

from pirlo.core.models.orchestrator import OrchestratorLink


class OrchestratorRepository(ABC):
    """Abstract port for persisting and retrieving orchestrator links."""

    @abstractmethod
    def save(self, link: OrchestratorLink) -> None:
        """Saves an OrchestratorLink or any concrete subclass (e.g. PrefectLink)."""
        ...

    @abstractmethod
    def get_by_name(self, name: str) -> OrchestratorLink | None:
        """Retrieves link by name, deserialized into its concrete subclass instance."""
        ...

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Deletes a link by its name. Returns True if deleted."""
        ...

    @abstractmethod
    def list_all(self) -> list[OrchestratorLink]:
        """Lists all registered concrete link instances."""
        ...
