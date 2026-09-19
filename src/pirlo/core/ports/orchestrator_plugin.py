from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.models.orchestrator import (
    OrchestratorLink,
    OrchestratorVerificationResult,
)
from pirlo.core.ports.runner import PlayRunner


class OrchestratorPlugin[OrchestratorLinkType: OrchestratorLink](ABC):
    """Abstract generic port for workflow engine plugins, parameterized by its link subclass."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Engine identifier this plugin handles ('prefect', 'airflow', etc.)."""
        ...

    @property
    @abstractmethod
    def link_cls(self) -> type[OrchestratorLinkType]:
        """Concrete OrchestratorLink subclass associated with this engine."""
        ...

    @abstractmethod
    def prompt_create_link(
        self, name: str, args: argparse.Namespace, interactive: bool
    ) -> OrchestratorLinkType:
        """Interactive CLI prompt & arg validation for creating a link of this engine type."""
        ...

    @abstractmethod
    def verify_connection(
        self, link: OrchestratorLinkType
    ) -> OrchestratorVerificationResult:
        """Verifies connectivity, authentication, and readiness of the orchestrator link."""
        ...

    @abstractmethod
    def create_runner(
        self, link: OrchestratorLinkType | None, **kwargs: Any
    ) -> PlayRunner:
        """Creates a PlayRunner instance configured for this orchestrator link (statically typed)."""
        ...
