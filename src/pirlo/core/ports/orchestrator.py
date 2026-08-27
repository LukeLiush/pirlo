from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from pirlo.core.models.link import LlmLink
from pirlo.core.models.run_result import RunResult

if TYPE_CHECKING:
    from pirlo.core.models.run import PreparedRun


class AutopassExecutionOptions(BaseModel):
    """Explicitly typed execution options for Autopass sessions."""

    playmaker: LlmLink = Field(description="LlmLink object for decision brain")
    analyst: LlmLink = Field(
        description="LlmLink object for DOM analysis & selector repair"
    )
    use_vision: bool = Field(default=False, description="Enable vision capabilities")
    max_failures: int = Field(
        default=5, description="Max failure attempts before stopping"
    )
    retry_delay: int = Field(default=10, description="Retry delay in seconds")
    generate_gif: bool = Field(
        default=False, description="Generate execution GIF artifact"
    )
    cron: str | None = Field(
        default=None,
        description="Optional cron schedule expression (e.g. '0 9 * * *')",
    )


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
