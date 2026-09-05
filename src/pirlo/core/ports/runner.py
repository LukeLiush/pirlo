# src/pirlo/core/ports/runner.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.models.blueprint import PlayOutput


class PlayRunner[WorkflowT](ABC):
    """Abstract Port for executing a workflow model."""

    @abstractmethod
    async def run(
        self,
        workflow: WorkflowT,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Executes the workflow and returns the output of the terminal Play node."""
        raise NotImplementedError
