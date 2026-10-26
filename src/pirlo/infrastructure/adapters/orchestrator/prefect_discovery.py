import os

from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)


def discover_prefect_server_url() -> str | None:
    """
    Discovers active Prefect server API URL from the PREFECT_API_URL environment variable.
    Returns API URL string (e.g. 'http://127.0.0.1:4200/api') or None if no server is active.
    """
    env_url = os.environ.get("PREFECT_API_URL")
    if env_url and is_prefect_healthy(env_url):
        return env_url

    # No server running -> Return None to trigger Ephemeral mode
    return None
