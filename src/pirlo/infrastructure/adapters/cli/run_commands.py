import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from pirlo.core.models.run import RunStatus
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)


def run_main():
    parser = argparse.ArgumentParser(
        description="Manage execution run history.", prog="pirlo run"
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # 1. list
    list_parser = subparsers.add_parser(
        "list", aliases=["ls"], help="List recent execution runs in descending order"
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Max number of runs to display (default: 10)",
    )
    list_parser.add_argument(
        "-s",
        "--status",
        type=str,
        default=None,
        help="Filter by status (e.g. completed, failed, started)",
    )
    list_parser.add_argument(
        "-p",
        "--playbook",
        type=str,
        default=None,
        help="Filter by playbook name (e.g. autopass, login)",
    )

    # 2. show
    show_parser = subparsers.add_parser(
        "show", aliases=["inspect"], help="Show detailed inspection of a specific run"
    )
    show_parser.add_argument("run_id", help="Unique Run ID to inspect")

    args = parser.parse_args(sys.argv[2:])

    subcommand = args.subcommand
    if not subcommand:
        # Default to list subcommand if pirlo run is called with no args
        run_list(limit=10, status=None, playbook=None)
    elif subcommand in ("list", "ls"):
        run_list(limit=args.limit, status=args.status, playbook=args.playbook)
    elif subcommand in ("show", "inspect"):
        run_show(args.run_id)


def get_repository() -> tuple[SqliteRunHistoryRepository, Path]:
    pirlo_workspace = Path(
        os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")
    ).expanduser()
    db_path = pirlo_workspace / "pirlo.db"
    if not db_path.exists():
        print(f"No execution database found at '{db_path}'. Run a playbook first.")
        sys.exit(0)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    repo = SqliteRunHistoryRepository(conn)
    return repo, pirlo_workspace


def format_duration(started_at: datetime | None, finished_at: datetime | None) -> str:
    if not started_at:
        return "N/A"
    end = finished_at or datetime.now(started_at.tzinfo)
    delta_sec = (end - started_at).total_seconds()
    if delta_sec < 60:
        return f"{delta_sec:.1f}s"
    mins = int(delta_sec // 60)
    secs = int(delta_sec % 60)
    return f"{mins}m {secs}s"


from rich import box
from rich.console import Console
from rich.table import Table


def format_status_markup(status: RunStatus) -> str:
    val = status.value.lower()
    text = status.value.upper()
    if val == "completed":
        return f"[bold green]{text}[/bold green]"
    elif val == "failed":
        return f"[bold red]{text}[/bold red]"
    elif val == "started":
        return f"[bold yellow]{text}[/bold yellow]"
    return f"[dim]{text}[/dim]"


def run_list(limit: int = 10, status: str | None = None, playbook: str | None = None):
    repo, _ = get_repository()
    runs = repo.list_runs(playbook=playbook, status=status, limit=limit)

    console = Console(width=None if sys.stdout.isatty() else 140)

    if not runs:
        console.print("[yellow]No execution runs found matching criteria.[/yellow]")
        return

    table = Table(
        title="Recent Execution Runs (Newest First)",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold white",
    )
    table.add_column("Run ID", style="bold white", no_wrap=True)
    table.add_column("Playbook", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Started At", style="dim", no_wrap=True)
    table.add_column("Duration", style="magenta", no_wrap=True)
    table.add_column("Task ID / Prompt", no_wrap=True)

    for run in runs:
        started_str = (
            run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "N/A"
        )
        duration_str = format_duration(run.started_at, run.finished_at)
        status_markup = format_status_markup(run.status)

        task_display = run.task_id
        if len(task_display) > 35:
            task_display = task_display[:32] + "..."

        table.add_row(
            run.run_id,
            run.playbook,
            status_markup,
            started_str,
            duration_str,
            task_display,
        )

    console.print(table)


def run_show(run_id: str):
    repo, pirlo_workspace = get_repository()
    run = repo.get_by_id(run_id)

    if not run:
        print(f"Error: Run ID '{run_id}' not found in database.", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print(f" Run Inspection: {run.run_id}")
    print("=" * 70)
    print(f"  • Playbook:         {run.playbook}")
    print(f"  • Task ID:          {run.task_id}")
    print(f"  • Run Type:         {run.run_type.value}")
    print(f"  • Status:           {run.status.value.upper()}")
    print(f"  • Created At:       {run.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if run.started_at:
        print(
            f"  • Started At:       {run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    if run.finished_at:
        print(
            f"  • Finished At:      {run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    print(f"  • Duration:         {format_duration(run.started_at, run.finished_at)}")

    # Parameter snapshot inspection
    param_path = run.get_parameter_location(pirlo_workspace)
    print(f"\nParameters Snapshot ({run.parameter_file_location}):")
    if param_path.exists():
        try:
            with open(param_path, "r", encoding="utf-8") as f:
                params = json.load(f)
            for k, v in params.items():
                print(f"  • {k:<18}: {v}")
        except Exception as e:  # noqa: BLE001
            print(f"  (Failed to parse params.json: {e})")
    else:
        print("  (No parameter file snapshot found)")

    # Step execution history inspection
    steps = repo.get_steps(run_id)
    if steps:
        print(f"\nStep Execution History ({len(steps)} steps):")
        for s in steps:
            st_symbol = "✓" if s["status"] == "completed" else "✗"
            goal_str = f" - Goal: {s['goal']}" if s.get("goal") else ""
            print(
                f"  [{st_symbol}] Step #{s['step_number']}: {s['action_type']}{goal_str}"
            )

    # Failure detail extraction
    if run.status == RunStatus.FAILED:
        print("\nError Details:")
        failed_steps = [s for s in steps if s["status"] != "completed"]
        if failed_steps:
            last_failed = failed_steps[-1]
            print(
                f"  • Failed Step:      Step #{last_failed['step_number']} [{last_failed['action_type']}]"
            )
            if last_failed.get("goal"):
                print(f"  • Failed Goal:      {last_failed['goal']}")

        log_path = run.get_log_location(pirlo_workspace)
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    log_text = f.read()

                if "Traceback (most recent call last):" in log_text:
                    tb_part = log_text.split("Traceback (most recent call last):")[
                        -1
                    ].strip()
                    tb_formatted = "\n".join(
                        f"    {line}" for line in tb_part.splitlines()[:25]
                    )
                    print(
                        f"  • Exception Traceback:\n    Traceback (most recent call last):\n{tb_formatted}"
                    )
                else:
                    log_lines = log_text.splitlines()
                    error_lines = [
                        line.strip()
                        for line in log_lines
                        if "ERROR" in line or "Exception" in line
                    ]
                    if error_lines:
                        print("  • Log Error Summary:")
                        for el in error_lines[-5:]:
                            print(f"    {el}")
            except Exception as e:  # noqa: BLE001
                print(f"  (Failed to read log file: {e})")

    # Artifact Discovery in run directory
    run_dir = pirlo_workspace / run.playbook / "runs" / run.run_id
    print(f"\nArtifacts & Recorded Logs ({run_dir}):")
    if run_dir.exists():
        artifacts = list(run_dir.glob("*"))
        if artifacts:
            for art in sorted(artifacts):
                print(f"  • {art.name:<20}: file://{art.resolve()}")
        else:
            print("  (No artifact files generated)")
    else:
        print("  (Run directory not created)")
    print()
