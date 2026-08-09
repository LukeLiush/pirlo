from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from pirlo.core.models.link import LlmLink
from pirlo.core.ports.pitch import Pitch


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
    """Abstract Port defining the orchestration contract for Pirlo tasks."""

    @abstractmethod
    async def execute(
        self,
        pitch: Pitch,
        worker_fn: Callable[[], Any],
    ) -> Any:
        """
        Executes an orchestrated workflow.
        Wraps pitch worker_fn in orchestration context (status tracking, logging, cron schedules).
        """
