from __future__ import annotations

import argparse

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
    assert plugin.engine_name == "prefect"
    assert plugin.link_cls is PrefectLink


def test_registry_case_insensitive() -> None:
    plugin = OrchestratorRegistry.get("PREFECT")
    assert isinstance(plugin, PrefectPlugin)


def test_registry_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="Unknown orchestrator engine 'nonexistent'"):
        OrchestratorRegistry.get("nonexistent")


def test_prefect_plugin_prompt_create_link() -> None:
    plugin = PrefectPlugin()
    args = argparse.Namespace(
        name="staging",
        server="http://prefect.staging:4200/api",
        work_pool="staging-pool",
    )
    link = plugin.prompt_create_link("staging", args, interactive=False)
    assert isinstance(link, PrefectLink)
    assert link.name == "staging"
    assert link.server_url == "http://prefect.staging:4200/api"
    assert link.work_pool == "staging-pool"


def test_prefect_plugin_create_runner_ephemeral() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(name="local", server_url="ephemeral")
    runner = plugin.create_runner(link)
    assert isinstance(runner, PrefectRunner)
    assert runner.mode == "ephemeral"
    assert runner.server_url is None


def test_prefect_plugin_create_runner_server() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.prod:4200/api",
        work_pool="prod-pool",
    )
    runner = plugin.create_runner(link)
    assert isinstance(runner, PrefectRunner)
    assert runner.mode == "server"
    assert runner.server_url == "http://prefect.prod:4200/api"
    assert runner.work_pool == "prod-pool"


def test_prefect_plugin_create_runner_none_default() -> None:
    plugin = PrefectPlugin()
    runner = plugin.create_runner(None)
    assert isinstance(runner, PrefectRunner)
    assert runner.mode == "ephemeral"
    assert runner.server_url is None
