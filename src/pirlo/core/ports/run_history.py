from abc import ABC, abstractmethod

from pirlo.core.models.run import Run


class RunHistoryRepository(ABC):
    """Abstract port for persisting execution history."""

    @abstractmethod
    def save(self, run: Run) -> None:
        """Saves a new run or updates an existing run."""

    @abstractmethod
    def get_by_id(self, run_id: str) -> Run | None:
        """Retrieves a run by its unique run_id."""

    @abstractmethod
    def list_runs(
        self, playbook: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Run]:
        """Lists runs with pagination, optionally filtered by playbook."""

    @abstractmethod
    def count_runs(self, playbook: str | None = None) -> int:
        """Returns total runs count for pagination."""
