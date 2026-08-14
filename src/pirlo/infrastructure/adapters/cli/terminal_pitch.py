from __future__ import annotations

import argparse
import asyncio
import sys
from abc import ABC
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from pirlo.core.config import get_workspace_path
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.playbook_invocation import PlaybookInvocation
from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.core.ports.pitch import Pitch
from pirlo.infrastructure.adapters.cli.argument_parser_builder import ArgumentParserBuilder
from pirlo.infrastructure.services.parameter_provider import ParameterProvider
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver


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

    def __init__(
            self,
            prepared_run: PreparedRun | None = None,
            orchestrator: TaskOrchestrator | None = None,
    ) -> None:
        super().__init__()
        self._console: Console = Console()
        self._prepared_run = prepared_run
        self.orchestrator = orchestrator

    @property
    def console(self) -> Console:
        if self._console is None:
            self._console = Console()
        return self._console

    async def prepared_run(self) -> PreparedRun:
        return self._prepared_run

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
        return await self.on_play()
        # from pirlo.core.models.run import RunStatus
        # from pirlo.core.models.run_result import RunResult
        #
        # # Delegate execution of self.on_play hook to orchestrator
        # schedule_value: str | None = self._prepared_run.parameters.get(self.schedule.name, None)
        # result = await self._prepared_run.orchestrator.execute(
        #     prepared_run=self._prepared_run,
        #     schedule=schedule_value,
        #     worker_fn=self.on_play,
        # )
        #
        # if isinstance(result, RunResult):
        #     return result
        #
        # return RunResult(
        #     run_id=self._prepared_run.run_id,
        #     status=RunStatus.COMPLETED,
        #     data=result,
        # )

    @classmethod
    def _discover_parameters(cls) -> list[Parameter]:
        """Collect every Parameter declared on the class."""
        return [
            attr_val
            for attr_name in dir(cls)
            if isinstance(attr_val := getattr(cls, attr_name), Parameter)
        ]

    @classmethod
    def _build_parser(
            cls,
            playbook_name: str,
            parameters: list[Parameter],
            epilog_text: str,
    ) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=f"pirlo {playbook_name}",
            description=cls.__doc__,
            epilog=epilog_text,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        for param in parameters:
            cls._add_argument_to_parser(parser, param.name, param)
        return parser

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
    def cli(cls, playbook_name: str = "autopass") -> RunResult[Any]:
        """Parse CLI parameters using the POSIX '--' delimiter and play the pitch."""
        from pirlo.infrastructure.adapters.cli.parameter_snapshot_writer import (
            ParameterSnapshotWriter,
        )
        from pirlo.infrastructure.adapters.cli.parameter_binder import ParameterBinder
        from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
        from pirlo.infrastructure.services.run_preparer import RunPreparer

        # 1. Normalize the raw invocation: strip command, ensure '--', split.
        raw_arguments: list[str] = extract_raw_arguments_excluding_command(sys.argv, playbook_name)
        playbook_invocation: PlaybookInvocation = PlaybookInvocation.from_raw(
            raw_arguments, default_orchestrator_name="prefect"
        )

        if not playbook_invocation.orchestrator_args:
            print("No orchestrator engine specified after '--'.", file=sys.stderr)
            sys.exit(1)

        orchestrator_name: str = playbook_invocation.orchestrator_args[0]
        pirlo_workspace: Path = get_workspace_path()

        # Step A: Prepare pure data run spec
        preparer: RunPreparer = RunPreparer(
            parameterizable_class=cls,
            pirlo_workspace=pirlo_workspace,
        )
        prepared_run: PreparedRun = preparer.prepare(
            playbook_name=playbook_name,
            playbook_invocation=playbook_invocation,
        )

        # Step B: Instantiate orchestrator engine service directly via OrchestratorFactory
        orchestrator: TaskOrchestrator = OrchestratorFactory.create_from_invocation(
            name=orchestrator_name,
            playbook_name=playbook_name,
            orchestrator_flags=playbook_invocation.orchestrator_args,
        )

        # Step C: Instantiate pitch with injected prepared_run
        terminal_pitch: TerminalPitch = cls(
            prepared_run=prepared_run,
        )

        playbook_parser: argparse.ArgumentParser = preparer._parser_builder.build_parser(
            playbook_name
        )
        parameter_resolver: ParameterResolver = ParameterResolver.create(
            playbook_parser=playbook_parser,
            playbook_invocation=playbook_invocation,
            pirlo_workspace=pirlo_workspace,
            toml_config={},
        )
        parameter_provider: ParameterProvider = ParameterProvider(parameter_resolver)
        parameter_binder: ParameterBinder = ParameterBinder(parameter_provider)
        parameter_snapshot_writer: ParameterSnapshotWriter = ParameterSnapshotWriter(parameter_provider)

        bound_pitch: TerminalPitch = parameter_binder.bind(terminal_pitch)  # type: ignore[assignment]
        bound_pitch.orchestrator = orchestrator
        parameter_snapshot_writer.write(bound_pitch, prepared_run.parameter_file_path)

        async def _play() -> RunResult[Any]:
            return await bound_pitch.on_play()

        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_play())
        else:
            return loop.create_task(_play())

    # --- Concrete Port Implementations ---

    def header(self, title: str, subtitle: str | None = None):
        text = f"[bold green]{title}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self._console.print(Panel(text, expand=False, border_style="cyan"))

    def status(self, message: str) -> Status:
        return self._console.status(
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
        self._console.print(tbl)

    async def var_check(self, message: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, input, f"🔍 [VAR CHECK] {message}: ")

    def goal(self, message: str, detail: str | None = None):
        text = f"⚽[bold green]GOAL! {message}[/bold green] "
        if detail:
            text += f"\n[cyan]{detail}[/cyan]"
        self._console.print(Panel(text, border_style="green", expand=False))

    def red_card(self, message: str, detail: str | None = None):
        text = f"🟥 [bold red]RED CARD! {message}[/bold red] "
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self._console.print(Panel(text, border_style="red", expand=False))

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
        self._console.print(Panel(text, border_style="yellow", expand=False))
