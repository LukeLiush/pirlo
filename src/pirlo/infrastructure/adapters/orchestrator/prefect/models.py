from __future__ import annotations

from typing import Annotated

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.models.orchestrator import OrchestratorLink, RoutineRegistration
from pirlo.core.models.parameters import Parameter


class PrefectLink(OrchestratorLink):
    """Prefect 3.x specific orchestrator connection."""

    server_url: Annotated[
        str,
        Parameter(
            help="Prefect API server URL or 'ephemeral' for local runs",
            short="-s",
        ),
    ] = "ephemeral"
    work_pool: Annotated[
        str,
        Parameter(
            help="Target work pool for scheduled routine deployments",
            short="-w",
        ),
    ] = DEFAULT_WORK_POOL

    @property
    def is_ephemeral(self) -> bool:
        return self.server_url == "ephemeral" or not self.server_url


class PrefectRoutineRegistration(RoutineRegistration):
    """Prefect-specific routine registration metadata."""

    work_pool: str = DEFAULT_WORK_POOL
    dashboard_url: str | None = None

    @property
    def orchestrator(self) -> str:
        return "prefect"
