# src/pirlo/playbooks/demo/report_dag.py
from __future__ import annotations

import asyncio
from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play, requires

# --- 1. Output Models ---


class DatesOutput(PlayOutput):
    report_dates: list[str]


class DownloadOutput(PlayOutput):
    file_path: str
    report_date: str


class MonthlySummary(PlayOutput):
    report_date: str
    revenue: float
    status_summary: str


class BudgetOutput(PlayOutput):
    target_revenue: float
    fiscal_quarter: str
    department: str


class SummaryOutput(PlayOutput):
    total_revenue: float
    target_revenue: float
    variance: float
    target_met: bool
    summaries: list[MonthlySummary]


class AlertOutput(PlayOutput):
    alert_sent: bool
    channel: str
    total_revenue: float
    target_revenue: float
    variance: float
    target_met: bool


# --- 2. Plays ---


@play(
    name="demo_select_dates",
    description="Selects target report periods for analysis",
)
class SelectReportDatesPlay(Play[DatesOutput]):
    async def execute(self) -> DatesOutput:
        self.ui.commentary("Selecting target quarterly report periods...")
        dates = ["2026-06", "2026-07", "2026-08"]
        self.ui.goal(
            message="Target periods selected", detail=f"Periods: {', '.join(dates)}"
        )
        return DatesOutput(report_dates=dates)


@play(
    name="demo_fetch_budget_target",
    description="Fetches quarterly budget revenue target from financial planning system",
)
class FetchBudgetTargetPlay(Play[BudgetOutput]):
    async def execute(
        self,
        quarter: Annotated[
            str, Parameter(help="Fiscal quarter for budget target")
        ] = "Q3-2026",
    ) -> BudgetOutput:
        self.ui.commentary(f"Fetching approved revenue budget for {quarter}...")
        await asyncio.sleep(0.5)
        target = 350000.00
        self.ui.goal(
            message=f"Budget target loaded for {quarter}",
            detail=f"Target: ${target:,.2f} (Dept: Global Sales)",
        )
        return BudgetOutput(
            target_revenue=target,
            fiscal_quarter=quarter,
            department="Global Sales",
        )


@play(
    name="demo_download_report",
    description="Downloads monthly PDF report concurrently from portal",
)
class DownloadReportPlay(Play[DownloadOutput]):
    # 1. Mapped individual date slice
    report_date: str = requires(SelectReportDatesPlay, each="report_dates")
    # 2. Broadcasted parent model
    dates: DatesOutput = requires(SelectReportDatesPlay)

    async def execute(self) -> DownloadOutput:
        # Simulated latencies: June takes 1.0s, July takes 2.0s, August takes 5.0s
        delays = {"2026-06": 1.0, "2026-07": 2.0, "2026-08": 5.0}
        simulated_delay = delays.get(self.report_date, 1.5)

        total_count = len(self.dates.report_dates)
        self.ui.commentary(
            f"Downloading {self.report_date} report (1 of {total_count}, delay: {simulated_delay}s)..."
        )
        await asyncio.sleep(simulated_delay)

        result = DownloadOutput(
            file_path=f"/tmp/reports/monthly_{self.report_date.replace('-', '_')}.pdf",
            report_date=self.report_date,
        )
        self.ui.goal(
            message=f"[{self.report_date}] Download finished in {simulated_delay}s",
            detail=result.file_path,
        )
        return result


@play(
    name="demo_extract_summary",
    description="Fans in monthly downloads and compares against quarterly budget target",
)
class ExtractSummaryPlay(Play[SummaryOutput]):
    # Multi-parent dependencies:
    # 1. Fanned-in mapped download outputs
    downloads: list[DownloadOutput] = requires(DownloadReportPlay)
    # 2. Parallel scalar budget target output
    budget: BudgetOutput = requires(FetchBudgetTargetPlay)

    async def execute(self) -> SummaryOutput:
        self.ui.commentary(
            f"Fanning in: extracting revenue stats across {len(self.downloads)} downloaded reports "
            f"and comparing to {self.budget.fiscal_quarter} target (${self.budget.target_revenue:,.2f})..."
        )
        monthly_revenues = {
            "2026-06": 110000.00,
            "2026-07": 118000.00,
            "2026-08": 125000.50,
        }
        summaries: list[MonthlySummary] = []
        total_revenue = 0.0

        for dl in sorted(self.downloads, key=lambda d: d.report_date):
            rev = monthly_revenues.get(dl.report_date, 100000.0)
            total_revenue += rev
            summaries.append(
                MonthlySummary(
                    report_date=dl.report_date,
                    revenue=rev,
                    status_summary=f"{dl.report_date}: ${rev:,.2f}",
                )
            )

        variance = total_revenue - self.budget.target_revenue
        target_met = variance >= 0.0
        status_tag = "EXCEEDED" if target_met else "MISSED"
        breakdown = " | ".join(s.status_summary for s in summaries)
        self.ui.goal(
            message=f"Summary extracted ({status_tag} target by ${abs(variance):,.2f})",
            detail=f"Breakdown: {breakdown} (Actual: ${total_revenue:,.2f} vs Target: ${self.budget.target_revenue:,.2f})",
        )
        return SummaryOutput(
            total_revenue=total_revenue,
            target_revenue=self.budget.target_revenue,
            variance=variance,
            target_met=target_met,
            summaries=summaries,
        )


@play(
    name="demo_report_dag",
    description="Merges summaries and broadcasts consolidated quarterly report alert",
)
class SendAlertPlay(Play[AlertOutput]):
    summary: SummaryOutput = requires(ExtractSummaryPlay)

    async def execute(
        self,
        channel: Annotated[str, Parameter(help="Target alert channel")] = "#finance",
    ) -> AlertOutput:
        status_text = (
            "Target Achieved 🎯" if self.summary.target_met else "Target Missed ⚠️"
        )
        self.ui.header(
            "Quarterly Report Alert",
            subtitle=f"Channel: {channel} | Status: {status_text}",
        )
        self.ui.commentary(
            f"📢 [{channel}] Q3 Consolidated Revenue: ${self.summary.total_revenue:,.2f} "
            f"(Target: ${self.summary.target_revenue:,.2f}, Variance: {self.summary.variance:+,.2f}) "
            f"across {len(self.summary.summaries)} months."
        )
        self.ui.goal(
            message=f"Alert sent successfully! ({status_text})",
            detail=f"Channel: {channel} | Revenue: ${self.summary.total_revenue:,.2f} | Variance: {self.summary.variance:+,.2f}",
        )
        return AlertOutput(
            alert_sent=True,
            channel=channel,
            total_revenue=self.summary.total_revenue,
            target_revenue=self.summary.target_revenue,
            variance=self.summary.variance,
            target_met=self.summary.target_met,
        )


if __name__ == "__main__":
    SendAlertPlay.cli()
