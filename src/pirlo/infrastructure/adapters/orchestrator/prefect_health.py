import httpx


def is_prefect_healthy(api_url: str, timeout_seconds: float = 0.3) -> bool:
    """Fast probe of a Prefect server's /api/health endpoint."""
    endpoint = f"{api_url.rstrip('/').removesuffix('/api')}/api/health"
    try:
        return httpx.get(endpoint, timeout=timeout_seconds).status_code == 200
    except httpx.HTTPError:
        return False
