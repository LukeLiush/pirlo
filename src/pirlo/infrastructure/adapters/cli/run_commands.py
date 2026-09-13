# src/pirlo/infrastructure/adapters/cli/run_commands.py
import argparse
import asyncio
import inspect
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from pirlo.core.config import get_workspace_path
from pirlo.core.models.run import PlayRunDetail, Run, RunStatus
from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
    PrefectRunRepository,
)


def get_repository() -> tuple[Any, Path]:
    """Returns the run repository and the active workspace path."""
    pirlo_workspace: Path = get_workspace_path()
    return PrefectRunRepository(), pirlo_workspace


def format_status_markup(status: RunStatus) -> str:
    val: str = status.value.lower()
    text: str = status.value.upper()
    if val == "completed":
        return f"[bold green]{text}[/bold green]"
    elif val == "failed":
        return f"[bold red]{text}[/bold red]"
    elif val in ("started", "running"):
        return f"[bold yellow]{text}[/bold yellow]"
    return f"[dim]{text}[/dim]"


def run_main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Manage execution run history.", prog="pirlo run"
    )
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser] = (
        parser.add_subparsers(dest="subcommand")
    )

    # 1. list
    list_parser: argparse.ArgumentParser = subparsers.add_parser(
        "list", aliases=["ls"], help="List recent execution runs"
    )
    list_parser.add_argument(
        "-n", "--limit", type=int, default=10, help="Max runs to display (default: 10)"
    )
    list_parser.add_argument(
        "-s", "--status", type=str, default=None, help="Filter by status"
    )
    list_parser.add_argument(
        "-p", "--playbook", type=str, default=None, help="Filter by playbook name"
    )

    # 2. show
    show_parser: argparse.ArgumentParser = subparsers.add_parser(
        "show", aliases=["inspect"], help="Inspect metadata and plays of a run"
    )
    show_parser.add_argument("run_id", help="8-character Run ID to inspect")

    # 3. log
    log_parser: argparse.ArgumentParser = subparsers.add_parser(
        "log", aliases=["logs"], help="Stream execution logs for a play"
    )
    log_parser.add_argument("target", help="Run ID or <run_id>/<play_id>")
    log_parser.add_argument(
        "-n",
        "--tail",
        type=int,
        default=None,
        help="Lines to tail (default: all lines)",
    )
    log_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow live logs in real time"
    )

    args: argparse.Namespace = parser.parse_args(sys.argv[2:])
    subcommand: str | None = args.subcommand

    if not subcommand or subcommand in ("list", "ls"):
        limit: int = getattr(args, "limit", 10)
        status: str | None = getattr(args, "status", None)
        playbook: str | None = getattr(args, "playbook", None)
        run_list(limit=limit, status=status, playbook=playbook)
    elif subcommand in ("show", "inspect"):
        run_show(args.run_id)
    elif subcommand in ("log", "logs"):
        target: str = args.target
        run_id: str
        play_id: str | None
        if "/" in target:
            run_id, play_id = target.split("/", 1)
        else:
            run_id, play_id = target, None
        tail_lines: int | None = args.tail
        if args.follow and tail_lines is None:
            tail_lines = 50
        run_log(run_id, play_id=play_id, tail_lines=tail_lines, follow=args.follow)


def run_list(
    limit: int = 10,
    status: str | None = None,
    playbook: str | None = None,
) -> None:
    repo: Any
    repo, _ = get_repository()
    res: Any = repo.list_runs(playbook=playbook, status=status, limit=limit)
    runs: list[Run] = (
        asyncio.run(cast(Coroutine[Any, Any, list[Run]], res))
        if inspect.isawaitable(res)
        else res
    )
    console: Console = Console(width=None if sys.stdout.isatty() else 140)

    if not runs:
        console.print(
            "[yellow]No execution runs found in Prefect orchestrator.[/yellow]"
        )
        return

    table: Table = Table(
        title="Recent Execution Runs (Newest First)",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Run ID", style="bold white", no_wrap=True)
    table.add_column("Playbook", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Started At", style="dim", no_wrap=True)
    table.add_column("Duration", style="magenta", no_wrap=True)
    table.add_column("Parameters", style="dim", no_wrap=True)

    run: Run
    for run in runs:
        started_str: str = (
            run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "N/A"
        )
        duration_str: str = (
            f"{run.duration:.1f}s" if run.duration is not None else "N/A"
        )
        domain_params: dict[str, Any] = {
            k: v for k, v in run.parameters.items() if k not in ("force", "run_name")
        }
        param_summary: str = ", ".join(
            f"{k}={v}" for k, v in list(domain_params.items())[:2]
        )
        if len(domain_params) > 2:
            param_summary += "..."

        table.add_row(
            run.run_id,
            run.playbook,
            format_status_markup(run.status),
            started_str,
            duration_str,
            param_summary or "---",
        )

    console.print(table)


def run_show(run_id: str) -> None:
    repo: Any
    workspace: Path
    repo, workspace = get_repository()
    res: Any = repo.get_by_id(run_id)
    run: Run | None = (
        asyncio.run(cast(Coroutine[Any, Any, Run | None], res))
        if inspect.isawaitable(res)
        else res
    )
    if not run:
        print(f"Error: Run ID '{run_id}' not found in Prefect.", file=sys.stderr)
        sys.exit(1)

    run_dir: Path = run.get_run_dir(workspace)

    console: Console = Console(width=None if sys.stdout.isatty() else 140)
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(
        f"[bold white] Run Inspection:[/bold white] [bold yellow]{run.run_id}[/bold yellow]"
    )
    console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")
    console.print(f"  • [bold]Playbook:[/bold]         {escape(run.playbook)}")
    console.print(
        f"  • [bold]Status:[/bold]           {format_status_markup(run.status)}"
    )
    if run.started_at:
        console.print(
            f"  • [bold]Started At:[/bold]       {run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    if run.finished_at:
        console.print(
            f"  • [bold]Finished At:[/bold]      {run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    dur: str = f"{run.duration:.1f}s" if run.duration is not None else "N/A"
    console.print(f"  • [bold]Duration:[/bold]         {dur}")
    if run.dashboard_url:
        console.print(f"  • [bold]Prefect UI:[/bold]       {run.dashboard_url}")
    console.print(f"  • [bold]Run Dir:[/bold]          file://{run_dir}")

    # 1. Parameters Snapshot
    console.print("\n[bold green]Parameters Snapshot:[/bold green]")
    domain_params: dict[str, Any] = {
        k: v for k, v in run.parameters.items() if k not in ("force", "run_name")
    }
    if domain_params:
        for k, v in domain_params.items():
            console.print(f"  • [dim]{k:<18}[/dim]: {v}")
    else:
        console.print("  (None or empty)")

    # 2. Plays Breakdown (Minimal Format)
    if run.play_runs:
        console.print(
            f"\n[bold blue]Plays in this Run ({len(run.play_runs)} plays):[/bold blue]"
        )
        i: int
        p: PlayRunDetail
        for i, p in enumerate(run.play_runs, start=1):
            badge: str
            if p.status == RunStatus.COMPLETED:
                badge = "[bold green][✓][/bold green]"
            elif p.status == RunStatus.FAILED:
                badge = "[bold red][✗][/bold red]"
            else:
                badge = "[bold yellow][◌][/bold yellow]"

            p_dur: str = f"({p.duration:.1f}s)" if p.duration is not None else ""
            escaped_play_id: str = f"{run.run_id}/{escape(p.play_id)}"
            console.print(f"  {badge} {i}. {escaped_play_id:<36} {p_dur}")

    # 3. Error Details (if failed)
    if run.status == RunStatus.FAILED and run.error_message:
        console.print("\n[bold red]Error Details:[/bold red]")
        console.print(f"  • {escape(run.error_message)}")

    # 4. Artifacts Discovery in run directory
    artifacts: list[Path] = []
    if run_dir.exists():
        artifacts.extend(
            p
            for p in run_dir.glob("*")
            if p.is_file() and not p.name.endswith(".cursor")
        )

    playbook_runs_dir: Path = workspace / run.playbook / "runs"
    has_workflow_artifact: bool = any(
        art.name.endswith(".json") and "workflow" in art.name for art in artifacts
    )
    if not has_workflow_artifact and playbook_runs_dir.exists():
        candidate_names: set[str] = set()
        if run.run_name:
            candidate_names.add(run.run_name)
        if "-" in run.run_id:
            parts: list[str] = run.run_id.split("-")
            if len(parts) >= 3 and "_" in parts[-1] and "_" in parts[-2]:
                candidate_names.add("-".join(parts[:-2]))
            elif len(parts) >= 2 and "_" in parts[-1]:
                candidate_names.add("-".join(parts[:-1]))

        for json_file in playbook_runs_dir.glob("*.json"):
            if any(name in json_file.name for name in candidate_names if name):
                artifacts.append(json_file)

    seen_paths: set[Path] = set()
    unique_artifacts: list[Path] = []
    for art in artifacts:
        resolved: Path = art.resolve()
        if resolved not in seen_paths:
            seen_paths.add(resolved)
            unique_artifacts.append(art)

    if unique_artifacts:
        console.print(f"\nArtifacts & Recorded Logs ({run_dir}):")
        for art in sorted(unique_artifacts, key=lambda p: p.name):
            console.print(f"  • {art.name:<25}: file://{art.resolve()}")

    failed_play: PlayRunDetail | None = next(
        (p for p in run.play_runs if p.status == RunStatus.FAILED), None
    )
    log_target: str
    if failed_play:
        log_target = f"{run.run_id}/{failed_play.play_id}"
    elif run.play_runs:
        log_target = f"{run.run_id}/{run.play_runs[0].play_id}"
    else:
        log_target = run.run_id

    console.print(
        f"\n[dim]💡 To stream logs for a play, run:[/dim] [bold cyan]pirlo run log {escape(log_target)}[/bold cyan]\n"
    )


def run_log(
    run_id: str,
    play_id: str | None = None,
    tail_lines: int | None = None,
    follow: bool = False,
) -> None:
    repo: PrefectRunRepository = PrefectRunRepository()

    async def _stream() -> None:
        try:
            async for line in repo.stream_play_logs(
                run_id, play_id=play_id, tail_lines=tail_lines, follow=follow
            ):
                print(line)
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_stream())
    except KeyboardInterrupt:
        pass
