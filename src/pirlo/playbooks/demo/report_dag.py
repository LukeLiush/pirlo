# src/pirlo/playbooks/demo/report_dag.py
from __future__ import annotations

from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play, requires

# --- 1. Sub-Play Output Models ---


class DownloadOutput(PlayOutput):
    file_path: str
    report_date: str


class SummaryOutput(PlayOutput):
    file_path: str
    total_revenue: float
    status_summary: str


class AlertOutput(PlayOutput):
    alert_sent: bool
    channel: str


# --- 2. Plays ---


@play(
    name="demo_download_report",
    description="Downloads monthly PDF report from portal",
)
class DownloadReportPlay(Play[DownloadOutput]):
    async def execute(
        self,
        report_month: Annotated[
            str, Parameter(help="Target month (YYYY-MM)")
        ] = "2026-08",
    ) -> DownloadOutput:
        self.ui.commentary(f"Downloading monthly report for {report_month}...")
        result = DownloadOutput(
            file_path=f"/tmp/reports/monthly_{report_month.replace('-', '_')}.pdf",
            report_date=f"{report_month}-31",
        )
        self.ui.goal(message="Report downloaded", detail=result.file_path)
        return result


@play(
    name="demo_extract_summary",
    description="Extracts revenue summary from downloaded report",
)
class ExtractSummaryPlay(Play[SummaryOutput]):
    download: DownloadOutput = requires(DownloadReportPlay)

    async def execute(self) -> SummaryOutput:
        self.ui.commentary(
            f"Extracting revenue stats from {self.download.file_path}..."
        )
        result = SummaryOutput(
            file_path=self.download.file_path,
            total_revenue=125000.50,
            status_summary=f"August Revenue: $125,000.50 (Target Exceeded by 15%) for {self.download.report_date}",
        )
        self.ui.goal(message="Summary extracted", detail=result.status_summary)
        return result


@play(
    name="demo_report_dag",
    description="Downloads report, extracts summary, and sends alert DAG",
)
class SendAlertPlay(Play[AlertOutput]):
    download: DownloadOutput = requires(DownloadReportPlay)
    summary: SummaryOutput = requires(ExtractSummaryPlay)

    async def execute(
        self,
        channel: Annotated[str, Parameter(help="Target alert channel")] = "#finance",
    ) -> AlertOutput:
        self.ui.header("Monthly Report Alert", subtitle=f"Channel: {channel}")
        self.ui.commentary(
            f"📢 [{channel}] Report {self.download.report_date}: {self.summary.status_summary}"
        )
        self.ui.goal(message="Alert sent successfully!", detail=f"Channel: {channel}")
        return AlertOutput(alert_sent=True, channel=channel)


if __name__ == "__main__":
    SendAlertPlay.cli()
