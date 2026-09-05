# tests/test_demo_report_dag.py
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pirlo.core.models.blueprint import BlueprintNode, PlaybookBlueprint
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.playbooks.demo.report_dag import (
    AlertOutput,
    SendAlertPlay,
)


def test_demo_report_dag_blueprint_extraction():
    dag = SendAlertPlay()
    blueprint: PlaybookBlueprint = dag.extract_blueprint()

    assert blueprint.name == "SendAlertPlay"
    assert len(blueprint.nodes) == 3

    node1: BlueprintNode = blueprint.nodes[0]
    assert node1.playbook_name == "DownloadReportPlay"
    assert node1.depends_on == []

    node2: BlueprintNode = blueprint.nodes[1]
    assert node2.playbook_name == "ExtractSummaryPlay"
    assert "download" in node2.param_bindings
    assert node2.param_bindings["download"].source_node_id == node1.node_id
    assert node2.depends_on == [node1.node_id]

    node3: BlueprintNode = blueprint.nodes[2]
    assert node3.playbook_name == "SendAlertPlay"
    assert "download" in node3.param_bindings
    assert node3.param_bindings["download"].source_node_id == node1.node_id
    assert "summary" in node3.param_bindings
    assert node3.param_bindings["summary"].source_node_id == node2.node_id
    assert node3.depends_on == [node1.node_id, node2.node_id]


def test_demo_report_dag_local_practice_run():
    result: AlertOutput = asyncio.run(
        SendAlertPlay.run_play(report_month="2026-09", channel="#testing")
    )

    assert isinstance(result, AlertOutput)
    assert result.alert_sent is True
    assert result.channel == "#testing"


def test_demo_report_dag_prefect_compilation():
    dag = SendAlertPlay()
    blueprint: PlaybookBlueprint = dag.extract_blueprint()

    master_flow: Callable[..., Any] = PrefectCompiler.compile(blueprint)
    assert master_flow is not None
    assert getattr(master_flow, "name", None) == blueprint.name
