import argparse
import asyncio
import inspect
import json
import os
import sys
from abc import ABC
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.pitch import LinkParameter, Parameter, Pitch
from pirlo.core.services.run_id_generator import generate_run_name


def extract_raw_arguments_excluding_command(
    sys_argv: list[str], playbook_name: str
) -> list[str]:
    """
    Strips binary and playbook command names from sys.argv.

    Examples:
      ['pirlo', 'autopass', '--task', 'x'] -> ['--task', 'x']
      ['pirlo autopass', '--task', 'x']    -> ['--task', 'x']
      ['pirlo', 'autopass', '--', 'prefect', '-h'] -> ['--', 'prefect', '-h']
    """
    raw_args = sys_argv[1:]
    if raw_args and raw_args[0] == playbook_name:
        raw_args = raw_args[1:]
    return raw_args


def ensure_canonical_orchestrator_delimiter(
    raw_arguments: list[str], default_orchestrator_name: str = "prefect"
) -> list[str]:
    """
    Ensures '-- <default_orchestrator_name>' is attached to raw CLI arguments if '--' is omitted.

    Examples:
      ['--task', 'Search'] -> ['--task', 'Search', '--', 'prefect']
      ['--task', 'Search', '--', 'prefect'] -> unchanged
    """
    if "--" not in raw_arguments:
        return raw_arguments + ["--", default_orchestrator_name]
    return raw_arguments


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
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    if type_func == Path:
        return Path(val).expanduser()

    try:
        return type_func(val)
    except (ValueError, TypeError):
        return val


class TerminalPitch(Pitch, ABC):
    """Concrete adapter of Pitch for Terminal screens."""

    schedule = Parameter(
        str,
        default=None,
        help=(
            "Optional schedule preset ('hourly', 'daily', 'weekly', 'monthly') "
            "or raw 5-field cron expression (e.g. '0 9 * * *' or '*/15 * * * *')"
        ),
        env_name="SCHEDULE",
        short="-s",
    )

    def __init__(self, run_id: str | None = None):
        super().__init__()
        self.console = Console()
        self._run_id: str | None = run_id
        self.run_dir: Any = None
        self._orchestrator_name: str = "prefect"
        self._orchestrator_options: dict[str, Any] = {}

    @property
    def domain_options(self) -> dict[str, Any]:
        """Dynamically collects all domain Parameter values directly from instance attributes."""
        options: dict[str, Any] = {}
        for attr_name in dir(self.__class__):
            attr_val = getattr(self.__class__, attr_name)
            if isinstance(attr_val, Parameter):
                options[attr_name] = getattr(self, attr_name)
        return options

    def _build_param_dict(self) -> dict[str, Any]:
        """Serializes domain options into JSON-encodable dictionary for hashing & persistence."""
        from pirlo.core.models.link import LlmLink

        param_dict = {}
        for k, v in self.domain_options.items():
            if isinstance(v, Path):
                param_dict[k] = str(v)
            elif isinstance(v, LlmLink):
                param_dict[k] = v.name
            else:
                param_dict[k] = v
        return param_dict

    @property
    def run_name(self) -> str:
        """Computes deterministic run_name on demand purely from domain options."""

        return generate_run_name(
            self._resolve_playbook_name(), self._build_param_dict()
        )

    @property
    def task_id(self) -> str:
        """Alias for run_name for backward compatibility."""
        return self.run_name

    @property
    def run_id(self) -> str:
        """Framework-managed execution run ID, lazily generated from run_name if not set."""
        if self._run_id is None:
            from pirlo.core.services.run_id_generator import generate_run_id

            self._run_id = generate_run_id(self.run_name)
        return self._run_id

    def _resolve_playbook_name(self) -> str:
        """Resolves the playbook name (e.g. 'AutopassSession' -> 'autopass')."""
        if sys.argv and len(sys.argv) > 1 and sys.argv[0].startswith("pirlo "):
            return sys.argv[0].split(" ")[1]
        name = self.__class__.__name__.lower()
        for suffix in ("session", "pitch", "playbook"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    async def on_play(self) -> RunResult[Any]:
        """
        Abstract extension hook implemented by playbook subclasses.
        Contains the playbook's core business logic (e.g. self-healing runner, login workflow).
        """
        raise NotImplementedError(
            f"Playbook class '{self.__class__.__name__}' must implement the on_play() method "
            "to define its core task logic."
        )

    async def play(self) -> RunResult[Any]:
        """
        Framework template method:
        1. Resolves requested orchestrator backend (default: 'prefect').
        2. Merges CLI parameter overrides (server_url, work_pool).
        3. Delegates execution of self.on_play() to orchestrator.execute().
        4. Normalizes and returns a structured RunResult.
        """
        from pirlo.core.models.run import RunStatus
        from pirlo.core.models.run_result import RunResult
        from pirlo.infrastructure.adapters.orchestrator.factory import (
            OrchestratorFactory,
        )

        orchestrator_name = getattr(self, "_orchestrator_name", "prefect")
        orchestrator_options = getattr(self, "_orchestrator_options", {})
        orchestrator = OrchestratorFactory.create(
            name=orchestrator_name,
            **orchestrator_options,
        )

        # Delegate execution of self.on_play hook to orchestrator
        result = await orchestrator.execute(
            self,
            worker_fn=self.on_play,
        )

        if isinstance(result, RunResult):
            return result

        return RunResult(
            run_id=self.run_id,
            status=RunStatus.COMPLETED,
            data=result,
        )

    @classmethod
    def _add_argument_to_parser(
        cls, parser: argparse.ArgumentParser, attr_name: str, attr_val: Parameter
    ) -> None:
        flag = f"--{attr_name.replace('_', '-')}"
        if flag in parser._option_string_actions:
            return

        kwargs: dict[str, Any] = {
            "help": attr_val.help,
            "default": argparse.SUPPRESS,
        }

        type_func = attr_val.type_func
        is_list = False
        origin = getattr(type_func, "__origin__", type_func)

        if origin is list:
            is_list = True
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

    @classmethod
    def cli(cls):
        """Parses CLI parameters using POSIX '--' delimiter and plays the pitch."""
        from pirlo.infrastructure.adapters.orchestrator.factory import (
            OrchestratorFactory,
        )

        instance = cls()
        playbook_name = instance._resolve_playbook_name()

        # 1. Attach default '-- prefect' if '--' is omitted, then split cleanly
        raw_arguments = extract_raw_arguments_excluding_command(sys.argv, playbook_name)
        canonical_arguments = ensure_canonical_orchestrator_delimiter(
            raw_arguments, default_orchestrator_name="prefect"
        )
        split_index = canonical_arguments.index("--")
        playbook_raw_arguments = canonical_arguments[:split_index]
        orchestrator_raw_arguments = canonical_arguments[split_index + 1 :]

        # 2. Build Playbook Parser (Parses playbook & schedule parameters)
        registered_orchestrators = OrchestratorFactory.list_orchestrators()
        available_orchestration_engines = ", ".join(
            sorted(registered_orchestrators.keys())
        )
        epilog_text = (
            "Orchestration Engines:\n"
            "  Use '-- <orchestrator> [options]' to specify an orchestrator engine backend.\n"
            f"  Available engines: {available_orchestration_engines}\n\n"
            "  Examples:\n"
            f'    pirlo {playbook_name} --task "Search" -- prefect -h\n'
            f'    pirlo {playbook_name} --task "Search" -- prefect --server-url http://localhost:4200/api\n'
        )

        playbook_parser = argparse.ArgumentParser(
            prog=f"pirlo {playbook_name}",
            description=cls.__doc__,
            epilog=epilog_text,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parameters: list[Parameter] = []
        for attr_name in dir(cls):
            attr_val = getattr(cls, attr_name)
            if isinstance(attr_val, Parameter):
                parameters.append(attr_val)
                cls._add_argument_to_parser(playbook_parser, attr_name, attr_val)

        parsed_playbook_args = playbook_parser.parse_args(playbook_raw_arguments)

        # 3. Parse Orchestrator Args (Engine name + Orchestrator flags)
        orchestrator_name = orchestrator_raw_arguments[0]
        orchestrator_flags = orchestrator_raw_arguments[1:]

        if orchestrator_name not in registered_orchestrators:
            instance.red_card(
                f"Unknown orchestrator engine '{orchestrator_name}'",
                detail=f"Available orchestrators: {available_orchestration_engines}",
            )
            sys.exit(1)

        orchestrator_class = registered_orchestrators[orchestrator_name]
        orchestrator_options = orchestrator_class.parse_cli_options(
            playbook_name=playbook_name,
            orchestrator_flags=orchestrator_flags,
        )

        # 4. Bind parsed playbook options following precedence: CLI > Env > pirlo.toml > Default
        link_repo = None
        for param in parameters:
            # 1. CLI argument
            if hasattr(parsed_playbook_args, param.name):
                val = getattr(parsed_playbook_args, param.name)
                val = convert_value(val, param.type_func)
            # 2. Environment Variable
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
            # 3. Default
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

            setattr(instance, param.name, val)

        instance._orchestrator_name = orchestrator_name
        instance._orchestrator_options = orchestrator_options

        # Auto-persist per-run parameter snapshot under runs/<run_id>/params.json
        from pirlo.core.config import get_workspace_path

        param_dict = instance._build_param_dict()
        pirlo_workspace = get_workspace_path()
        run_dir = pirlo_workspace / playbook_name / "runs" / instance.run_id
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

        if inspect.iscoroutinefunction(instance.play):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                return loop.create_task(instance.play())
            else:
                return asyncio.run(instance.play())
        else:
            return instance.play()

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

    def yellow_card(self, message: Any, detail: str | None = None):
        if hasattr(message, "message"):
            msg_str = message.message
            det_str = getattr(message, "detail", detail)
        else:
            msg_str = str(message)
            det_str = detail

        text = f"🟨 [bold yellow]YELLOW CARD: {msg_str}[/bold yellow] "
        if det_str:
            text += f"\n[dim]{det_str}[/dim]"
        self.console.print(Panel(text, border_style="yellow", expand=False))
