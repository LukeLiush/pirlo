import argparse
import asyncio
import inspect
import json
import os
import sqlite3
import sys
from abc import ABC
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from pirlo.core.ports.pitch import LinkParameter, Parameter, Pitch


def convert_value(val: Any, type_func: Callable) -> Any:
    if val is None:
        return None

    origin = getattr(type_func, "__origin__", type_func)
    if origin is list:
        # Extract item type, default to str
        type_args = getattr(type_func, "__args__", ())
        item_type = type_args[0] if type_args else str
        if isinstance(val, str):
            # Try to parse as JSON first (e.g. '["a", "b"]')
            try:
                parsed_list = json.loads(val)
                if isinstance(parsed_list, list):
                    return [convert_value(item, item_type) for item in parsed_list]
            except json.JSONDecodeError as e:
                if val.strip().startswith("["):
                    sys.stderr.write(
                        f"Warning: Failed to decode list parameter as JSON: {e}\n"
                    )
            # Fall back to comma-separated split
            if not val.strip():
                return []
            return [convert_value(item.strip(), item_type) for item in val.split(",")]
        elif isinstance(val, list):
            return [convert_value(item, item_type) for item in val]
        else:
            return [convert_value(val, item_type)]

    if origin is dict:
        if isinstance(val, str):
            try:
                parsed_dict = json.loads(val)
                if isinstance(parsed_dict, dict):
                    return parsed_dict
            except json.JSONDecodeError as e:
                if val.strip().startswith("{"):
                    sys.stderr.write(
                        f"Warning: Failed to decode dict parameter as JSON: {e}\n"
                    )
        return dict(val) if val else {}

    if type_func == bool:
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    try:
        return type_func(val)
    except (ValueError, TypeError):
        return val


class TerminalPitch(Pitch, ABC):
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
                    "help": attr_val.help,
                    "default": argparse.SUPPRESS,
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
            "--config",
            help=(
                "Path to a JSON config file containing parameter key-values "
                '(e.g. {"playmaker": "my-qwen", "task": "..."}). CLI flags override config file values.'
            ),
        )
        parsed_args = parser.parse_args()

        run_id = parsed_args.run_id
        repo = None
        run = None

        if run_id:
            from pirlo.core.config import get_workspace_path
            from pirlo.core.models.run import RunStatus
            from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
                SqliteRunHistoryRepository,
            )

            pirlo_workspace = get_workspace_path()
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
        config_path_str = getattr(parsed_args, "config", None)

        if config_path_str:
            config_path = Path(config_path_str).expanduser()
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:  # noqa: BLE001
                    print(
                        f"Warning: Failed to load config from {config_path}: {e}",
                        file=sys.stderr,
                    )

        link_repo = None

        for param in parameters:
            # 1. CLI argument (highest priority)
            if hasattr(parsed_args, param.name):
                val = getattr(parsed_args, param.name)
                val = convert_value(val, param.type_func)
            # 2. Config file (JSON preset)
            elif param.name in config_data:
                val = config_data[param.name]
                val = convert_value(val, param.type_func)
            # 3. Environment Variable
            elif getattr(param, "env_name", None):
                env_names = (
                    [param.env_name]
                    if isinstance(param.env_name, str)
                    else param.env_name
                )
                env_val = None
                for env_name in env_names:
                    if env_name in os.environ:
                        env_val = os.environ[env_name]
                        break
                if env_val is not None:
                    val = convert_value(env_val, param.type_func)
                else:
                    val = param.default
            # 4. Default
            else:
                val = param.default

            # Resolve LinkParameter into LlmLink domain object
            if isinstance(param, LinkParameter):
                if val:
                    if link_repo is None:
                        from pirlo.infrastructure.adapters.storage.json_link_repository import (
                            JsonLinkRepository,
                        )

                        links_file = Path("~/.pirlo-pitch/links.json").expanduser()
                        link_repo = JsonLinkRepository(links_file)

                    link_obj = link_repo.get_by_name(val)
                    if not link_obj:
                        flag_name = f"--{param.name.replace('_', '-')}"
                        instance.red_card(
                            f"Missing required link '{val}' for parameter '{flag_name}'",
                            detail="Run 'pirlo link list' to check available links or 'pirlo link create' to register a new link.",
                        )
                        sys.exit(1)
                    val = link_obj
                else:
                    val = None

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

        from pirlo.core.models.link import LlmLink
        from pirlo.core.services.run_id_generator import generate_task_id

        param_dict = {}
        for k, v in instance._parsed_options.items():
            if isinstance(v, Path):
                param_dict[k] = str(v)
            elif isinstance(v, LlmLink):
                param_dict[k] = v.name
            else:
                param_dict[k] = v
        instance.task_id = generate_task_id(playbook_name, param_dict)

        # Auto-persist per-run parameter snapshot under runs/<run_id>/params.json
        from pirlo.core.services.run_id_generator import generate_run_id

        effective_run_id = run_id or generate_run_id(instance.task_id)
        from pirlo.core.config import get_workspace_path

        pirlo_workspace = get_workspace_path()
        run_dir = pirlo_workspace / playbook_name / "runs" / effective_run_id
        instance.run_id = effective_run_id
        instance.run_dir = run_dir
        run_params_path = run_dir / "params.json"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            with open(run_params_path, "w", encoding="utf-8") as f:
                json.dump(param_dict, f, indent=4)
        except Exception as e:  # noqa: BLE001
            print(
                f"Warning: Failed to save per-run parameter snapshot to {run_params_path}: {e}",
                file=sys.stderr,
            )

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
                    except Exception as e:  # noqa: BLE001
                        print(
                            f"Warning: Failed to close repository connection: {e}",
                            file=sys.stderr,
                        )

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
        text = f"⚽[bold green]GOAL! {message}[/bold green] "
        if detail:
            text += f"\n[cyan]{detail}[/cyan]"
        self.console.print(Panel(text, border_style="green", expand=False))

    def red_card(self, message: str, detail: str | None = None):
        text = f"🟥 [bold red]RED CARD! {message}[/bold red] "
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self.console.print(Panel(text, border_style="red", expand=False))

    def yellow_card(self, message: str, detail: str | None = None):
        text = f"🟨 [bold yellow]YELLOW CARD: {message}[/bold yellow] "
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self.console.print(Panel(text, border_style="yellow", expand=False))
