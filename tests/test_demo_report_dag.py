# tests/test_demo_report_dag.py
from __future__ import annotations

import asyncio
from typing import Any, Callable

from pirlo.core.models.blueprint import BlueprintNode, PlaybookBlueprint
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.playbooks.demo.report_dag import (
    AlertOutput,
    ReportDownloadDAG,
)


def test_demo_report_dag_blueprint_extraction():
    dag = ReportDownloadDAG()
    blueprint: PlaybookBlueprint = dag.extract_blueprint()

    assert blueprint.name == "ReportDownloadDAG"
    assert len(blueprint.nodes) == 3

    node1: BlueprintNode = blueprint.nodes[0]
    assert node1.playbook_name == "DownloadReportPlaybook"
    assert node1.static_kwargs == {"report_month": "2026-08"}

    node2: BlueprintNode = blueprint.nodes[1]
    assert node2.playbook_name == "ExtractSummaryPlaybook"
    assert "file_path" in node2.param_bindings
    assert node2.param_bindings["file_path"].source_node_id == node1.node_id
    assert node2.depends_on == [node1.node_id]

    node3: BlueprintNode = blueprint.nodes[2]
    assert node3.playbook_name == "SendAlertPlaybook"
    assert "report_date" in node3.param_bindings
    assert node3.param_bindings["report_date"].source_node_id == node1.node_id
    assert "status_summary" in node3.param_bindings
    assert node3.param_bindings["status_summary"].source_node_id == node2.node_id
    assert node3.depends_on == [node1.node_id, node2.node_id]


def test_demo_report_dag_local_practice_run():
    dag = ReportDownloadDAG()
    result: AlertOutput = asyncio.run(
        dag.play(report_month="2026-09", channel="#testing")
    )

    assert isinstance(result, AlertOutput)
    assert result.alert_sent is True
    assert result.channel == "#testing"


def test_demo_report_dag_prefect_compilation():
    dag = ReportDownloadDAG()
    blueprint: PlaybookBlueprint = dag.extract_blueprint()

    master_flow: Callable[..., Any] = PrefectCompiler.compile(blueprint)
    assert master_flow is not None
    assert getattr(master_flow, "name", None) == blueprint.name
