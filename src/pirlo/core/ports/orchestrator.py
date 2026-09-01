from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pirlo.core.decorators import orchestrator
from pirlo.core.models.run_result import RunResult

if TYPE_CHECKING:
    from pirlo.core.models.run import PreparedRun


@dataclass(frozen=True)
class OrchestratorInfo:
    """Structured metadata for an orchestrator backend engine."""

    name: str
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class TaskOrchestrator(ABC):
    """Abstract port definition for execution engine backends (Prefect, Local, etc.)."""

    info: ClassVar[OrchestratorInfo]

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if not hasattr(cls, "info"):
            raise TypeError(
                f"Orchestrator class '{cls.__name__}' is missing the @{orchestrator.__name__} decorator."
            )
        return super().__new__(cls)

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
