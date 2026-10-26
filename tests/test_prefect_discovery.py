from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)


def test_is_prefect_healthy_unreachable():
    assert is_prefect_healthy("http://127.0.0.1:59999/api") is False


def test_discover_server_url_fallback(monkeypatch):
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.is_prefect_healthy",
        lambda url, timeout_seconds=0.3: False,
    )
    assert discover_prefect_server_url() is None


def test_discover_server_url_env_active(monkeypatch):
    target_url = "http://127.0.0.1:4200/api"
    monkeypatch.setenv("PREFECT_API_URL", target_url)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.is_prefect_healthy",
        lambda url, timeout_seconds=0.3: url == target_url,
    )
    assert discover_prefect_server_url() == target_url
