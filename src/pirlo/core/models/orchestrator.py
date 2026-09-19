from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from pirlo.core.models.parameters import Parameter

ROUTINE_PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


class OrchestratorLink(BaseModel, ABC):
    """Abstract Pydantic base model for named orchestrator connections."""

    model_config = ConfigDict(frozen=True)

    name: Annotated[
        str,
        Parameter(
            help="Unique link name (e.g. prod, staging)",
            short="-n",
        ),
    ]
    engine: str = ""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return

        for field_name, field_info in cls.model_fields.items():
            if field_name in ("name", "engine"):
                continue
            has_param = any(isinstance(m, Parameter) for m in field_info.metadata)
            if not has_param:
                raise TypeError(
                    f"Invalid field '{field_name}' on {cls.__name__}: "
                    f"OrchestratorLink fields must be annotated with Parameter, e.g.:\n"
                    f"  {field_name}: Annotated[str, Parameter(help='...')] = 'default'"
                )


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
