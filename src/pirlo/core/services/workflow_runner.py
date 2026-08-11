from abc import ABC, abstractmethod


class WorkflowRunner(ABC):
    """Abstract base class (interface) representing a workflow execution engine."""

    @abstractmethod
    async def run(
        self,
        task_prompt: str,
        cache_key: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Executes the workflow given the task prompt, cache key, and run ID."""
