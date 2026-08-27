from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pirlo.core.models.run_result import RunResult

if TYPE_CHECKING:
    from pirlo.core.models.run import PreparedRun


class TaskOrchestrator(ABC):
    """Abstract port definition for execution engine backends (Prefect, Local, etc.)."""

    orchestrator_name: str = ""

    @classmethod
    def get_name(cls) -> str:
        return getattr(cls, "orchestrator_name", cls.__name__.lower())

    @abstractmethod
    async def execute(
        self,
        prepared_run: PreparedRun,
        worker_fn: Callable[[], Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any] | Any:
        """
        Abstract execution hook implemented by orchestrator subclasses.
        Subclasses declare orchestrator-specific CLI flags after '--' in their execute() signature.
        """
        raise NotImplementedError
