from __future__ import annotations

import pytest

from pirlo.infrastructure.adapters.orchestrator.prefect.models import PrefectLink
from pirlo.infrastructure.adapters.orchestrator.prefect.plugin import (
    PrefectPlugin,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
    PrefectRunner,
)
from pirlo.infrastructure.adapters.orchestrator.registry import (
    OrchestratorRegistry,
)


def test_registry_discovers_prefect() -> None:
    engines = OrchestratorRegistry.list_engines()
    assert "prefect" in engines

    plugin = OrchestratorRegistry.get("prefect")
    assert isinstance(plugin, PrefectPlugin)

    link_cls = OrchestratorRegistry.get_orchestrator_link_cls("prefect")
    assert link_cls is PrefectLink
    # Default engine property configured automatically on the model
    assert link_cls.model_fields["engine"].default == "prefect"


def test_registry_case_insensitive() -> None:
    plugin = OrchestratorRegistry.get("PREFECT")
    assert isinstance(plugin, PrefectPlugin)
    link_cls = OrchestratorRegistry.get_orchestrator_link_cls("PREFECT")
    assert link_cls is PrefectLink


def test_registry_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="Unknown orchestrator engine 'nonexistent'"):
        OrchestratorRegistry.get("nonexistent")
    with pytest.raises(ValueError, match="Unknown orchestrator engine 'nonexistent'"):
        OrchestratorRegistry.get_orchestrator_link_cls("nonexistent")


def test_prefect_plugin_create_runner_ephemeral() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(name="local", server_url="ephemeral")
    runner = plugin.create_runner(link)
    assert isinstance(runner, PrefectRunner)
    assert runner.link.is_ephemeral is True


def test_prefect_plugin_create_runner_server() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.prod:4200/api",
        work_pool="prod-pool",
    )
    runner = plugin.create_runner(link)
    assert isinstance(runner, PrefectRunner)
    assert runner.link.is_ephemeral is False
    assert runner.link.server_url == "http://prefect.prod:4200/api"
    assert runner.link.work_pool == "prod-pool"


def test_prefect_plugin_create_runner_none_default() -> None:
    plugin = PrefectPlugin()
    runner = plugin.create_runner(None)
    assert isinstance(runner, PrefectRunner)
    assert runner.link.is_ephemeral is True
