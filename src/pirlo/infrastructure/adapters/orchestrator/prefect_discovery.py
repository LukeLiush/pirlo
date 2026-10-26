import contextlib
import os

from pirlo.core.config import get_workspace_path
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)


def discover_prefect_server_url() -> str | None:
    """
    Discovers active Prefect server API URL.
    Checks:
      1. PREFECT_API_URL environment variable
      2. Active pirlo connect session (connect/session.json)
    Returns API URL string (e.g. 'http://127.0.0.1:39823/api') or None if no server is active.
    """
    # 1. Check explicit environment variable
    env_url = os.environ.get("PREFECT_API_URL")
    if env_url and is_prefect_healthy(env_url):
        return env_url

    # 2. Check active pirlo connect session (connect/session.json)
    with contextlib.suppress(Exception):
        from pirlo.core.models.serve_manifest import ActiveSession

        connect_session = ActiveSession.load_active(
            get_workspace_path() / "connect" / "session.json"
        )
        if connect_session and is_prefect_healthy(connect_session.prefect_api_url):
            return connect_session.prefect_api_url

    # 3. No server running -> Return None to trigger Ephemeral mode
    return None
