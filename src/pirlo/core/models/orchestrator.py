from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

ROUTINE_PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


class RoutineRegistration(BaseModel, ABC):
    """Generic base model for the result of registering a recurring routine."""

    model_config = ConfigDict(frozen=True)

    registration_id: str
    play_name: str
    routine: str | None = None

    @property
    @abstractmethod
    def orchestrator(self) -> str:
        """Subclasses MUST implement this to define their orchestrator name (e.g. 'prefect')."""
        ...
