# src/pirlo/core/ports/runner.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput

if TYPE_CHECKING:
    from pirlo.core.models.orchestrator import RoutineRegistration


class PlayRunner(ABC):
    """Abstract Port for executing a workflow model."""

    @abstractmethod
    async def run(
        self,
        blueprint: PlayBlueprint,
        *,
        routine: str | None = None,
        force: bool = False,
        show_logs: bool = False,
        **kwargs: Any,
    ) -> PlayOutput | RoutineRegistration | None:
        """Executes the workflow immediately or registers a recurring routine."""
        raise NotImplementedError

    @abstractmethod
    def get_dashboard_url(self, run_id: str) -> str | None:
        """Returns the orchestrator-specific web UI URL for inspecting this run, or None if local/ephemeral."""
        raise NotImplementedError
