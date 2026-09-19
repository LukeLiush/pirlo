from pydantic import Field

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.models.orchestrator import OrchestratorLink, RoutineRegistration


class PrefectLink(OrchestratorLink):
    """Prefect 3.x specific orchestrator connection."""

    server_url: str = Field(
        default="ephemeral",
        description="Prefect API server URL or 'ephemeral' for local runs",
    )
    work_pool: str = Field(
        default=DEFAULT_WORK_POOL,
        description="Target work pool for scheduled routine deployments",
    )

    @property
    def engine(self) -> str:
        return "prefect"

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
