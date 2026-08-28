from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pirlo.core.models.execution_context import DEFAULT_CONTEXT, ExecutionContext

PageT = TypeVar("PageT")


class WorkflowRunner(ABC, Generic[PageT]):  # noqa: UP046
    """Abstract base class (interface) representing a workflow execution engine."""

    @abstractmethod
    async def run(
        self,
        task_prompt: str,
        context: ExecutionContext[PageT] = DEFAULT_CONTEXT,
    ) -> str:
        """Executes the workflow given the task prompt and execution context."""
