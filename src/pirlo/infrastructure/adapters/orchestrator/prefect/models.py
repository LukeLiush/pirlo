from __future__ import annotations

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.models.orchestrator import RoutineRegistration


class PrefectRoutineRegistration(RoutineRegistration):
    """Prefect-specific routine registration metadata."""

    work_pool: str = DEFAULT_WORK_POOL
    dashboard_url: str | None = None

    @property
    def orchestrator(self) -> str:
        return "prefect"
