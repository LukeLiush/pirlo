import argparse
import asyncio
import inspect
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from pirlo.core.ports.pitch import Parameter, Pitch


class TerminalPitch(Pitch):
    """Concrete adapter of Pitch for Terminal screens."""

    def __init__(self):
        super().__init__()
        self.console = Console()

    @classmethod
    def cli(cls):
        """Parses CLI parameters and plays the pitch."""
        instance = cls()
        parser = argparse.ArgumentParser(description=cls.__doc__)
        parameters: list[Parameter] = []

        # Extract declared Parameters
        for attr_name in dir(cls):
            attr_val = getattr(cls, attr_name)
            if isinstance(attr_val, Parameter):
                parameters.append(attr_val)
                flag = f"--{attr_name.replace('_', '-')}"
                kwargs = {
                    "default": attr_val.default,
                    "help": attr_val.help,
                }

                # Check if the type is a list or list-like generic alias (e.g. list[str])
                type_func = attr_val.type_func
                is_list = False
                origin = getattr(type_func, "__origin__", type_func)

                if origin is list:
                    is_list = True
                    # Extract the item type, default to str if not specified (e.g. list[str] -> str)
                    type_args = getattr(type_func, "__args__", ())
                    type_func = type_args[0] if type_args else str

                if type_func == bool:
                    kwargs["action"] = "store_true"
                else:
                    kwargs["type"] = type_func
                    if is_list:
                        kwargs["nargs"] = "*"

                if attr_val.short:
                    parser.add_argument(attr_val.short, flag, **kwargs)
                else:
                    parser.add_argument(flag, **kwargs)

        parser.add_argument("--run-id", help="The unique execution run ID")
        parser.add_argument(
            "--config", help="Path to a JSON configuration file containing parameters"
        )
        parsed_args = parser.parse_args()

        run_id = parsed_args.run_id
        repo = None
        run = None

        if run_id:
            from pirlo.core.models.run import RunStatus
            from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
                SqliteRunHistoryRepository,
            )

            pirlo_workspace = Path(
                os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")
            ).expanduser()
            db_path = pirlo_workspace / "pirlo.db"
            try:
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                repo = SqliteRunHistoryRepository(conn)
                run = repo.get_by_id(run_id)
                if run:
                    run.status = RunStatus.STARTED
                    run.started_at = datetime.now(UTC)
                    run.updated_at = datetime.now(UTC)
                    repo.save(run)
            except Exception as e:  # noqa: BLE001
                print(
                    f"Warning: Failed to update run status to STARTED: {e}",
                    file=sys.stderr,
                )

        config_data = {}
        if getattr(parsed_args, "config", None):
            config_path = Path(parsed_args.config)
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:  # noqa: BLE001
                    print(
                        f"Warning: Failed to load config from {config_path}: {e}",
                        file=sys.stderr,
                    )

        for param in parameters:
            if param.name in config_data:
                val = config_data[param.name]
                if val is not None and param.type_func in (Path, int, float):
                    val = param.type_func(val)
            else:
                val = getattr(parsed_args, param.name)
            instance._parsed_options[param.name] = val

        # Compute task_id deterministically based on playbook and parameters
        playbook_name = "unknown"
        if sys.argv and sys.argv[0].startswith("pirlo "):
            playbook_name = sys.argv[0].split(" ")[1]
        else:
            playbook_name = cls.__name__.lower()
            if playbook_name.endswith("session"):
                playbook_name = playbook_name[:-7]
            elif playbook_name.endswith("pitch"):
                playbook_name = playbook_name[:-5]

        from pirlo.core.services.run_id_generator import generate_task_id

        param_dict = {}
        for k, v in instance._parsed_options.items():
            if isinstance(v, Path):
                param_dict[k] = str(v)
            else:
                param_dict[k] = v
        instance.task_id = generate_task_id(playbook_name, param_dict)

        try:
            if inspect.iscoroutinefunction(instance.play):
                asyncio.run(instance.play())
            else:
                instance.play()
        finally:
            if run_id and run and repo:
                try:
                    from pirlo.core.models.run import RunStatus

                    run.status = RunStatus.COMPLETED
                    run.finished_at = datetime.now(UTC)
                    run.updated_at = datetime.now(UTC)
                    repo.save(run)
                except Exception as e:  # noqa: BLE001
                    print(
                        f"Warning: Failed to update run status to COMPLETED: {e}",
                        file=sys.stderr,
                    )
                finally:
                    try:
                        repo.conn.close()
                    except Exception:  # noqa: BLE001, S110
                        pass

    # --- Concrete Port Implementations ---

    def header(self, title: str, subtitle: str | None = None):
        text = f"[bold green]{title}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self.console.print(Panel(text, expand=False, border_style="cyan"))

    def status(self, message: str) -> Status:
        return self.console.status(
            f"[bold green]{message}[/bold green]", spinner="dots"
        )

    def lineup(self, title: str, columns: list[str], rows: list[list[str]]):
        tbl = Table(
            title=title,
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
        )
        for col in columns:
            tbl.add_column(col)
        for row in rows:
            tbl.add_row(*row)
        self.console.print(tbl)

    async def var_check(self, message: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, input, f"🔍 [VAR CHECK] {message}: ")

    def goal(self, message: str, detail: str | None = None):
        text = f"⚽ [bold green]GOAL! {message}[/bold green]"
        if detail:
            text += f"\n[cyan]{detail}[/cyan]"
        self.console.print(Panel(text, border_style="green", expand=False))

    def red_card(self, message: str, detail: str | None = None):
        text = f"🟥 [bold red]RED CARD! {message}[/bold red]"
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self.console.print(Panel(text, border_style="red", expand=False))

    def yellow_card(self, message: str, detail: str | None = None):
        text = f"🟨 [bold yellow]YELLOW CARD: {message}[/bold yellow]"
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self.console.print(Panel(text, border_style="yellow", expand=False))
