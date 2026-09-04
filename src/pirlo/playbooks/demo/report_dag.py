# src/pirlo/playbooks/demo/report_dag.py
from __future__ import annotations

from typing import Annotated, cast

from pirlo.core.decorators import playbook
from pirlo.core.models.blueprint import PlaybookOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.playbook import Playbook, PlayerNode

# --- 1. Sub-Playbook Output Models ---


class DownloadOutput(PlaybookOutput):
    file_path: str
    report_date: str


class SummaryOutput(PlaybookOutput):
    file_path: str
    total_revenue: float
    status_summary: str


class AlertOutput(PlaybookOutput):
    alert_sent: bool
    channel: str


# --- 2. Individual Sub-Playbooks ---


# @playbook(
#     name="demo_download_report",
#     description="Downloads monthly PDF report from portal",
# )
class DownloadReportPlaybook(Playbook[DownloadOutput]):
    async def play(
        self,
        report_month: Annotated[
            str, Parameter(help="Target month (YYYY-MM)")
        ] = "2026-08",
    ) -> DownloadOutput:
        # Simulates downloading a report file...
        return DownloadOutput(
            file_path=f"/tmp/reports/monthly_{report_month.replace('-', '_')}.pdf",
            report_date=f"{report_month}-31",
        )


# @playbook(
#     name="demo_extract_summary",
#     description="Extracts revenue summary from downloaded report",
# )
class ExtractSummaryPlaybook(Playbook[SummaryOutput]):
    async def play(
        self,
        file_path: Annotated[str, Parameter(help="Path to report PDF file")] = "",
    ) -> SummaryOutput:
        # Simulates extracting summary stats...
        return SummaryOutput(
            file_path=file_path,
            total_revenue=125000.50,
            status_summary="August Revenue: $125,000.50 (Target Exceeded by 15%)",
        )


# @playbook(
#     name="demo_send_alert", description="Sends summary notification alert"
# )
class SendAlertPlaybook(Playbook[AlertOutput]):
    async def play(
        self,
        report_date: Annotated[str, Parameter(help="Report date")] = "",
        status_summary: Annotated[str, Parameter(help="Summary text")] = "",
        channel: Annotated[str, Parameter(help="Target alert channel")] = "#reports",
    ) -> AlertOutput:
        # Simulates sending a Slack/Email alert...
        print(f"📢 [{channel}] Report {report_date}: {status_summary}")
        return AlertOutput(alert_sent=True, channel=channel)


# --- 3. Parent DAG Workflow ---


@playbook(
    name="demo_report_dag",
    description="Downloads report, extracts summary, and sends alert DAG",
)
class ReportDownloadDAG(Playbook[AlertOutput]):
    async def play(
        self,
        report_month: Annotated[str, Parameter(help="Target report month")] = "2026-08",
        channel: Annotated[str, Parameter(help="Alert channel name")] = "#finance",
    ) -> AlertOutput:
        # Step 1: Download Report
        player_download: PlayerNode = self.player(
            cast(type[Playbook[PlaybookOutput]], DownloadReportPlaybook),
            report_month=report_month,
        )

        # Step 2: Extract Summary (depends on player_download.ball.file_path)
        player_extract: PlayerNode = self.player(
            cast(type[Playbook[PlaybookOutput]], ExtractSummaryPlaybook),
            file_path=player_download.ball.file_path,
        ).after(player_download)

        # Step 3: Send Alert (depends on player_download & player_extract)
        self.player(
            cast(type[Playbook[PlaybookOutput]], SendAlertPlaybook),
            report_date=player_download.ball.report_date,
            status_summary=player_extract.ball.status_summary,
            channel=channel,
        ).after(player_download, player_extract)

        # Kickoff the match!
        return cast(
            AlertOutput,
            await self.kickoff(),
        )


if __name__ == "__main__":
    ReportDownloadDAG.cli()
