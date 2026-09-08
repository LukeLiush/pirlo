from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pirlo.core.models.run import Run


class RunRepository(ABC):
    """Abstract port for querying execution run history."""

    @abstractmethod
    async def list_runs(
        self,
        playbook: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[Run]:
        """Lists recent runs in descending order."""

    @abstractmethod
    async def get_by_id(self, run_id: str) -> Run | None:
        """Retrieves a run and its executed plays by 8-character run_id."""

    @abstractmethod
    def stream_play_logs(
        self,
        run_id: str,
        play_id: str | None = None,
        tail_lines: int = 50,
        follow: bool = False,
    ) -> AsyncIterator[str]:
        """Streams logs for a specific play_id with local file bookkeeping and cursor resume."""
