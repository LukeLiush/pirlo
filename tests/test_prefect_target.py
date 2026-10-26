from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
    Execution,
    PrefectTarget,
    resolve_default_target,
)


def test_ephemeral_target_has_no_server():
    target = PrefectTarget.ephemeral()

    assert target.execution is Execution.EPHEMERAL
    assert target.server.api_url is None
    assert target.server.web_ui_base is None


def test_ephemeral_target_uses_default_pool_and_storage_for_routines():
    target = PrefectTarget.ephemeral()

    assert target.work_pool == DEFAULT_WORK_POOL
    assert target.code_storage == "prefect_artifact"


# --- choosing the default target --------------------------------------------

_DISCOVER = (
    "pirlo.infrastructure.adapters.orchestrator.prefect_settings."
    "discover_prefect_server_url"
)


def _server_mode(monkeypatch, discovered: str | None) -> list[int]:
    calls: list[int] = []

    def fake_discover() -> str | None:
        calls.append(1)
        return discovered

    monkeypatch.setenv("PIRLO_SERVER", "auto")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_DISCOVER, fake_discover)
    return calls


def test_pirlo_server_off_wins_without_asking_for_a_server(monkeypatch):
    calls = _server_mode(monkeypatch, "http://h:4200/api")
    monkeypatch.setenv("PIRLO_SERVER", "off")

    target = resolve_default_target()

    assert target.execution is Execution.EPHEMERAL
    assert calls == []


def test_ci_forces_ephemeral(monkeypatch):
    calls = _server_mode(monkeypatch, "http://h:4200/api")
    monkeypatch.setenv("CI", "true")

    assert resolve_default_target().execution is Execution.EPHEMERAL
    assert calls == []


def test_configured_server_that_answers_runs_in_process(monkeypatch):
    _server_mode(monkeypatch, "http://h:4200")

    target = resolve_default_target()

    assert target.execution is Execution.IN_PROCESS
    assert target.server.api_url == "http://h:4200/api"


def test_no_server_found_stays_ephemeral(monkeypatch):
    _server_mode(monkeypatch, None)

    assert resolve_default_target().execution is Execution.EPHEMERAL


def test_factory_runner_uses_the_resolved_target(monkeypatch):
    from pirlo.infrastructure.adapters.runner_factory import PlayRunnerFactory

    _server_mode(monkeypatch, "http://h:4200/api")

    runner = PlayRunnerFactory.get_runner()

    assert runner.get_dashboard_url("r1") == "http://h:4200/flow-runs?name=r1"
