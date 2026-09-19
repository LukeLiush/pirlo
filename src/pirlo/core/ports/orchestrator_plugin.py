from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.models.orchestrator import (
    OrchestratorLink,
    OrchestratorVerificationResult,
)
from pirlo.core.ports.runner import PlayRunner


class OrchestratorPlugin[OrchestratorLinkType: OrchestratorLink](ABC):
    """Abstract generic port for workflow engine plugins, parameterized by its link subclass."""

    @abstractmethod
    def verify(self, link: OrchestratorLinkType) -> OrchestratorVerificationResult:
        """Verifies connectivity, authentication, and readiness of the orchestrator link."""
        ...

    @abstractmethod
    def create_runner(
        self, link: OrchestratorLinkType | None, **kwargs: Any
    ) -> PlayRunner:
        """Creates a PlayRunner instance configured for this orchestrator link (statically typed)."""
        ...
