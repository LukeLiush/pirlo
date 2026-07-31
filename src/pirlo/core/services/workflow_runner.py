from abc import ABC, abstractmethod


class WorkflowRunner(ABC):
    """Abstract base class (interface) representing a workflow execution engine."""

    @abstractmethod
    async def run(self, task_prompt: str, workflow_id: str | None = None) -> str:
        """Executes the workflow given the task prompt and an optional workflow ID."""
