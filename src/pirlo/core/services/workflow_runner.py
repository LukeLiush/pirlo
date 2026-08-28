from abc import ABC, abstractmethod
from typing import Any


class WorkflowRunner(ABC):
    """Abstract base class (interface) representing a workflow execution engine."""

    @abstractmethod
    async def run(
        self,
        task_prompt: str,
        page: Any | None = None,
        cache_key: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Executes the workflow given the task prompt, optional page, cache key, and run ID."""
