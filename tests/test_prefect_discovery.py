from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    check_health,
    discover_prefect_server_url,
)


def test_check_health_unreachable():
    # Probing a random unopened port returns False
    assert check_health("http://127.0.0.1:59999/api") is False


def test_discover_server_url_fallback(monkeypatch):
    # Ensure env var is cleared and candidate ports return False
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.check_health",
        lambda url: False,
    )
    assert discover_prefect_server_url() is None


def test_discover_server_url_env_active(monkeypatch):
    target_url = "http://127.0.0.1:4200/api"
    monkeypatch.setenv("PREFECT_API_URL", target_url)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.check_health",
        lambda url: url == target_url,
    )
    assert discover_prefect_server_url() == target_url
