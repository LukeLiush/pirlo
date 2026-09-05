# tests/test_play_parameter_bubbling.py
from __future__ import annotations

import asyncio
from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlaybookBlueprint, PlaybookOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play, requires
from pirlo.core.ports.playbook import each
from pirlo.core.services.blueprint_extractor import (
    BlueprintExtractor,
)
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)

# --- Test Output Models & Play Definitions ---


class FileDownloadOutput(PlaybookOutput):
    file_path: str
    month: str


class FileSummaryOutput(PlaybookOutput):
    total: float
    summary_text: str


class AlertDispatchedOutput(PlaybookOutput):
    sent: bool
    channel: str


@play(name="test_download", description="Download mock file")
class MockDownloadPlay(Play[FileDownloadOutput]):
    async def execute(
        self,
        report_month: Annotated[str, Parameter(help="Month to download")] = "2026-08",
    ) -> FileDownloadOutput:
        self.ui.commentary(f"Mock downloading file for month {report_month}")
        return FileDownloadOutput(
            file_path=f"/tmp/{report_month}.pdf",
            month=report_month,
        )


@play(name="test_extract", description="Extract mock summary")
class MockExtractPlay(Play[FileSummaryOutput]):
    download: FileDownloadOutput = requires(MockDownloadPlay)

    async def execute(
        self,
        multiplier: Annotated[float, Parameter(help="Revenue multiplier")] = 2.0,
    ) -> FileSummaryOutput:
        self.ui.commentary(f"Extracting stats from file: {self.download.file_path}")
        return FileSummaryOutput(
            total=500.0 * multiplier,
            summary_text=f"Summary for {self.download.month} with total {500.0 * multiplier}",
        )


@play(name="test_alert", description="Send mock alert")
class MockAlertPlay(Play[AlertDispatchedOutput]):
    download: FileDownloadOutput = requires(MockDownloadPlay)
    summary: FileSummaryOutput = requires(MockExtractPlay)

    async def execute(
        self,
        channel: Annotated[str, Parameter(help="Target channel")] = "#testing",
    ) -> AlertDispatchedOutput:
        self.ui.commentary(f"Sending alert to {channel}")
        self.ui.goal(message="Alert dispatched!", detail=self.summary.summary_text)
        return AlertDispatchedOutput(sent=True, channel=channel)


# --- Tests ---


def test_pull_extractor_strategy():
    """Verify that PullBasedPlayExtractorStrategy resolves the full DAG backwards."""
    blueprint: PlaybookBlueprint = BlueprintExtractor.extract_from_play(MockAlertPlay)

    assert blueprint.name == "MockAlertPlay"
    assert len(blueprint.nodes) == 3

    node_names = [n.playbook_name for n in blueprint.nodes]
    # Topological order: Download first, then Extract, then Alert
    assert node_names == ["MockDownloadPlay", "MockExtractPlay", "MockAlertPlay"]

    # Download has no dependencies
    assert blueprint.nodes[0].depends_on == []

    # Extract depends on Download
    assert blueprint.nodes[1].depends_on == [blueprint.nodes[0].node_id]
    assert "download" in blueprint.nodes[1].param_bindings

    # Alert depends on both Download and Extract
    assert set(blueprint.nodes[2].depends_on) == {
        blueprint.nodes[0].node_id,
        blueprint.nodes[1].node_id,
    }
    assert "download" in blueprint.nodes[2].param_bindings
    assert "summary" in blueprint.nodes[2].param_bindings
    assert blueprint.output_node_id == blueprint.nodes[2].node_id


def test_cli_argument_groups():
    """Verify that ArgumentParserBuilder bubbles upstream parameters into separate argument groups."""
    builder = ArgumentParserBuilder(MockAlertPlay)
    parser = builder.build_parser(prog_name="test_alert")

    group_titles = [g.title for g in parser._action_groups]
    assert any("Target Play Options (MockAlertPlay)" in title for title in group_titles)
    assert any(
        "Upstream Dependency Options (MockExtractPlay)" in title
        for title in group_titles
    )
    assert any(
        "Upstream Dependency Options (MockDownloadPlay)" in title
        for title in group_titles
    )

    # Check that parameters are bubbled into the parser
    param_names = [p["name"] for p in builder.parameters]
    assert "channel" in param_names
    assert "multiplier" in param_names
    assert "report_month" in param_names


def test_pull_based_prefect_execution():
    """Verify that a pull-based DAG executes end-to-end via Prefect in ephemeral mode."""
    result = asyncio.run(
        MockAlertPlay.run_play(report_month="2026-10", multiplier=3.0, channel="#ops")
    )

    assert isinstance(result, AlertDispatchedOutput)
    assert result.sent is True
    assert result.channel == "#ops"


class AggregatedQuarterOutput(PlaybookOutput):
    quarter_count: int
    files: list[str]


@play(name="test_quarterly_aggregate", description="Dynamic fan-in aggregate")
class MockQuarterlyAggregatePlay(Play[AggregatedQuarterOutput]):
    downloads: list[FileDownloadOutput] = requires(
        MockDownloadPlay,
        report_month=each(["2026-01", "2026-02", "2026-03"]),
    )

    async def execute(self) -> AggregatedQuarterOutput:
        file_list = [d.file_path for d in self.downloads]
        return AggregatedQuarterOutput(
            quarter_count=len(self.downloads),
            files=file_list,
        )


def test_dynamic_fan_in_prefect_execution():
    """Verify dynamic mapping using each(...) inside requires(...) with Prefect compilation."""
    result = asyncio.run(MockQuarterlyAggregatePlay.run_play())

    assert isinstance(result, AggregatedQuarterOutput)
    assert result.quarter_count == 3
    assert result.files == ["/tmp/2026-01.pdf", "/tmp/2026-02.pdf", "/tmp/2026-03.pdf"]
