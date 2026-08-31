from pirlo.core.ports.health_checker import PrefectHealthChecker
from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)


def test_prefect_health_checker_check_url_unreachable():
    assert PrefectHealthChecker.check_url("http://127.0.0.1:59999/api") is False


def test_discover_server_url_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.PrefectHealthChecker.check_url",
        lambda url, timeout_seconds=0.3: False,
    )
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.get_workspace_path",
        lambda: tmp_path,
    )
    assert discover_prefect_server_url() is None


def test_discover_server_url_env_active(monkeypatch):
    target_url = "http://127.0.0.1:4200/api"
    monkeypatch.setenv("PREFECT_API_URL", target_url)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.PrefectHealthChecker.check_url",
        lambda url, timeout_seconds=0.3: url == target_url,
    )
    assert discover_prefect_server_url() == target_url


def test_discover_server_url_connect_session_active(monkeypatch, tmp_path):
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.get_workspace_path",
        lambda: tmp_path,
    )

    from pirlo.core.models.serve_manifest import ActiveSession

    session = ActiveSession(
        remote_host="example.com",
        local_prefect_port=39823,
        local_ollama_port=11434,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
    )
    monkeypatch.setattr(
        "pirlo.core.models.serve_manifest.ActiveSession.load_active",
        lambda filepath: session,
    )
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.PrefectHealthChecker.check_url",
        lambda url, timeout_seconds=0.3: url == "http://127.0.0.1:39823/api",
    )

    assert discover_prefect_server_url() == "http://127.0.0.1:39823/api"
