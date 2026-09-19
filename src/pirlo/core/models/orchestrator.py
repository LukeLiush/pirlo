from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROUTINE_PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


class OrchestratorLink(BaseModel, ABC):
    """Abstract Pydantic base model for named orchestrator connections."""

    model_config = ConfigDict(frozen=True)

    name: str

    @property
    @abstractmethod
    def engine(self) -> str:
        """Subclasses MUST implement this to define their engine identifier (e.g. 'prefect')."""
        ...

    def to_dict(self) -> dict[str, str]:
        """Serializes flat string attributes including engine, excluding None."""
        data = {k: str(v) for k, v in self.model_dump(exclude_none=True).items()}
        data["engine"] = self.engine
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict[str, str]) -> OrchestratorLink:
        """Polymorphic factory resolving concrete link subclass via OrchestratorRegistry."""
        from pirlo.infrastructure.adapters.orchestrator.registry import (
            OrchestratorRegistry,
        )

        engine = data.get("engine", "prefect")
        plugin = OrchestratorRegistry.get(engine)
        return plugin.link_cls.model_validate({"name": name, **data})


class RoutineRegistration(BaseModel, ABC):
    """Generic base model for the result of registering a recurring routine."""

    model_config = ConfigDict(frozen=True)

    registration_id: str
    play_name: str
    routine: str

    @property
    @abstractmethod
    def orchestrator(self) -> str:
        """Subclasses MUST implement this to define their orchestrator name (e.g. 'prefect')."""
        ...


class OrchestratorVerificationResult(BaseModel):
    """Result of an orchestrator connectivity, authentication, and readiness check."""

    model_config = ConfigDict(frozen=True)

    success: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
