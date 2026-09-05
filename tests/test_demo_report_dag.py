# tests/test_demo_report_dag.py
from __future__ import annotations

import asyncio

from pirlo.core.models.blueprint import BlueprintNode, PlayBlueprint
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.playbooks.demo.report_dag import (
    AlertOutput,
    SendAlertPlay,
)


def test_demo_report_dag_blueprint_extraction():
    dag = SendAlertPlay()
    blueprint: PlayBlueprint = dag.extract_blueprint()

    assert blueprint.name == "SendAlertPlay"
    assert len(blueprint.nodes) == 5

    node_map: dict[str, BlueprintNode] = {n.playbook_name: n for n in blueprint.nodes}
    assert set(node_map.keys()) == {
        "SelectReportDatesPlay",
        "DownloadReportPlay",
        "FetchBudgetTargetPlay",
        "ExtractSummaryPlay",
        "SendAlertPlay",
    }

    dates_node = node_map["SelectReportDatesPlay"]
    assert dates_node.depends_on == []

    budget_node = node_map["FetchBudgetTargetPlay"]
    assert budget_node.depends_on == []

    download_node = node_map["DownloadReportPlay"]
    assert download_node.is_mapped is True
    assert "report_date" in download_node.mapped_bindings
    assert (
        download_node.mapped_bindings["report_date"].source_node_id
        == dates_node.node_id
    )
    assert download_node.mapped_bindings["report_date"].source_field == "report_dates"
    assert "dates" in download_node.param_bindings
    assert download_node.param_bindings["dates"].source_node_id == dates_node.node_id
    assert download_node.depends_on == [dates_node.node_id]

    summary_node = node_map["ExtractSummaryPlay"]
    assert "downloads" in summary_node.param_bindings
    assert (
        summary_node.param_bindings["downloads"].source_node_id == download_node.node_id
    )
    assert "budget" in summary_node.param_bindings
    assert summary_node.param_bindings["budget"].source_node_id == budget_node.node_id
    assert set(summary_node.depends_on) == {download_node.node_id, budget_node.node_id}

    alert_node = node_map["SendAlertPlay"]
    assert "summary" in alert_node.param_bindings
    assert alert_node.param_bindings["summary"].source_node_id == summary_node.node_id
    assert alert_node.depends_on == [summary_node.node_id]


def test_demo_report_dag_local_practice_run():
    # Test execution via Prefect runner (ephemeral)
    result: AlertOutput = asyncio.run(SendAlertPlay.run_play(channel="#testing"))
    assert isinstance(result, AlertOutput)
    assert result.alert_sent is True
    assert result.channel == "#testing"
    assert result.total_revenue == 353000.50
    assert result.target_revenue == 350000.00
    assert result.variance == 3000.50
    assert result.target_met is True


def test_demo_report_dag_prefect_compilation():
    dag = SendAlertPlay()
    blueprint: PlayBlueprint = dag.extract_blueprint()

    prefect_workflow = PrefectCompiler().compile(blueprint)
    assert prefect_workflow is not None
    assert prefect_workflow.name == blueprint.name
    assert callable(prefect_workflow.flow)
