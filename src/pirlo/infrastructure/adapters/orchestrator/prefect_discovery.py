import logging

from prefect.settings import Settings

from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)

logger = logging.getLogger(__name__)


def discover_prefect_server_url() -> str | None:
    """Returns the configured Prefect API URL if that server answers, else None.

    Reads PREFECT_API_URL fresh from the environment and the active Prefect
    profile (`prefect config set`), so values set after import are seen.
    """
    configured = Settings().api.url
    if not configured:
        return None
    if is_prefect_healthy(configured):
        return configured
    logger.warning(
        "Prefect server at %s isn't responding; using a temporary local server instead.",
        configured,
    )
    return None
