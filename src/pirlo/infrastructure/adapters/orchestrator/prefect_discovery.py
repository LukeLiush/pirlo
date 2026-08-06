import contextlib
import json
import os
from pathlib import Path

import httpx


def check_health(api_url: str) -> bool:
    """Fast health probe with 300ms timeout."""
    try:
        health_endpoint = f"{api_url.rstrip('/')}/health"
        res = httpx.get(health_endpoint, timeout=0.3)
        return res.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def discover_prefect_server_url() -> str | None:
    """
    Automatically discovers active local Prefect server API URL.
    Probes env var, ~/.prefect/profiles.json, and candidate ports.
    Returns API URL string (e.g. 'http://127.0.0.1:4200/api') or None if no server running.
    """
    # 1. Check explicit environment variable
    env_url = os.environ.get("PREFECT_API_URL")
    if env_url and check_health(env_url):
        return env_url

    # 2. Inspect active Prefect profile config (~/.prefect/profiles.json)
    profile_path = Path("~/.prefect/profiles.json").expanduser()
    if profile_path.exists():
        with contextlib.suppress(Exception):
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            active_profile = data.get("active", "default")
            profiles = data.get("profiles", {})
            profile_cfg = profiles.get(active_profile, {})
            prof_url = profile_cfg.get("PREFECT_API_URL")
            if prof_url and check_health(prof_url):
                return prof_url

    # 3. Probe candidate ports (4200, 4201, 4202, 4203)
    candidate_ports = [4200, 4201, 4202, 4203]
    for port in candidate_ports:
        url = f"http://127.0.0.1:{port}/api"
        if check_health(url):
            return url

    # 4. No server running -> Return None to trigger Ephemeral mode
    return None
