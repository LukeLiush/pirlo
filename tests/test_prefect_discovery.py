import logging

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


_HEALTH = (
    "pirlo.infrastructure.adapters.orchestrator.prefect_discovery.is_prefect_healthy"
)


def test_discover_reads_url_from_active_prefect_profile(monkeypatch, tmp_path):
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        'active = "dev"\n'
        "[profiles.dev]\n"
        'PREFECT_API_URL = "http://127.0.0.1:4888/api"\n'
    )
    monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles))
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    monkeypatch.setattr(_HEALTH, lambda url, timeout_seconds=0.3: True)

    assert discover_prefect_server_url() == "http://127.0.0.1:4888/api"


def test_discover_warns_when_configured_server_is_down(monkeypatch, caplog):
    monkeypatch.setenv("PREFECT_API_URL", "http://127.0.0.1:4999/api")
    monkeypatch.setattr(_HEALTH, lambda url, timeout_seconds=0.3: False)

    with caplog.at_level(logging.WARNING):
        assert discover_prefect_server_url() is None
    assert "http://127.0.0.1:4999/api" in caplog.text


def _serve_running(monkeypatch, api_url: str) -> None:
    """Records a live pirlo serve (this test process) whose server answers."""
    import os

    from pirlo.infrastructure.adapters.orchestrator.serve_beacon import (
        ServeBeacon,
        ServeRecord,
    )

    ServeBeacon().write(
        ServeRecord(
            pid=os.getpid(),
            port=4200,
            api_url=api_url,
            worker="desk",
            started_at="2026-01-01T00:00:00+00:00",
        )
    )
    monkeypatch.setattr(_BEACON_HEALTH, lambda url, timeout_seconds=0.3: True)


_BEACON_HEALTH = (
    "pirlo.infrastructure.adapters.orchestrator.serve_beacon.is_prefect_healthy"
)


def test_discover_uses_the_server_pirlo_serve_runs(monkeypatch):
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    _serve_running(monkeypatch, "http://127.0.0.1:4200/api")

    assert discover_prefect_server_url() == "http://127.0.0.1:4200/api"


def test_configured_server_wins_over_the_served_one(monkeypatch):
    monkeypatch.setenv("PREFECT_API_URL", "http://127.0.0.1:4999/api")
    monkeypatch.setattr(_HEALTH, lambda url, timeout_seconds=0.3: True)
    _serve_running(monkeypatch, "http://127.0.0.1:4200/api")

    assert discover_prefect_server_url() == "http://127.0.0.1:4999/api"


def test_no_configured_or_served_server_means_none(monkeypatch):
    monkeypatch.delenv("PREFECT_API_URL", raising=False)

    assert discover_prefect_server_url() is None
