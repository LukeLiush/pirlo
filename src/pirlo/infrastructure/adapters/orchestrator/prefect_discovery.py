import logging

from prefect.settings import Settings

from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)
from pirlo.infrastructure.adapters.orchestrator.serve_beacon import ServeBeacon

logger = logging.getLogger(__name__)


def discover_prefect_server_url() -> str | None:
    """Returns the Prefect API URL runs should report to, or None for a temporary server.

    A configured server wins: PREFECT_API_URL, read fresh from the environment
    and the active Prefect profile (`prefect config set`). If none is
    configured, the server `pirlo serve` started is used when it is running.
    """
    configured = Settings().api.url
    if configured:
        if is_prefect_healthy(configured):
            return configured
        logger.warning(
            "Prefect server at %s isn't responding; using a temporary local server instead.",
            configured,
        )
        return None
    served = ServeBeacon().running()
    return served.api_url if served else None
