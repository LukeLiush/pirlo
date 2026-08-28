from __future__ import annotations

import argparse
import asyncio
import sys
from abc import ABC
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from pirlo.core.config import get_workspace_path
from pirlo.core.models.playbook_invocation import PlaybookInvocation
from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.core.ports.pitch import Pitch
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.services.parameter_provider import ParameterProvider
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver


def extract_raw_arguments_excluding_command(
    sys_argv: list[str], playbook_name: str
) -> list[str]:
    """Strips binary and playbook command names from sys.argv."""
    raw_args = sys_argv[1:]
    if raw_args and raw_args[0] == playbook_name:
        raw_args = raw_args[1:]
    return raw_args


def ensure_canonical_orchestrator_delimiter(
    raw_arguments: list[str], default_orchestrator_name: str = "prefect"
) -> list[str]:
    """Ensures '-- <default_orchestrator_name>' is attached to raw CLI arguments if '--' is omitted."""
    if "--" not in raw_arguments:
        return raw_arguments + ["--", default_orchestrator_name]
    return raw_arguments


class TerminalPitch(Pitch, ABC):
    """Concrete adapter of Pitch for Terminal screens."""

    def __init__(
        self,
        prepared_run: PreparedRun | None = None,
        orchestrator: TaskOrchestrator | None = None,
    ) -> None:
        super().__init__()
        self._console: Console = Console()
        self._prepared_run = prepared_run
        self._orchestrator = orchestrator

    @property
    def console(self) -> Console:
        if self._console is None:
            self._console = Console()
        return self._console

    @property
    def orchestrator(self) -> TaskOrchestrator:
        assert self._orchestrator is not None
        return self._orchestrator

    @orchestrator.setter
    def orchestrator(self, value: TaskOrchestrator) -> None:
        self._orchestrator = value

    async def prepared_run(self) -> PreparedRun:
        assert self._prepared_run is not None
        return self._prepared_run

    async def play(self, *args: Any, **kwargs: Any) -> RunResult[Any]:
        """
        Abstract extension hook implemented by playbook subclasses.
        Contains the playbook's core business logic.
        """
        raise NotImplementedError(
            f"Playbook class '{self.__class__.__name__}' must implement the play() method."
        )

    @classmethod
    def cli(cls, playbook_name: str | None = None) -> RunResult[Any]:
        """Parse CLI parameters using the POSIX '--' delimiter and play the pitch."""
        from pirlo.infrastructure.adapters.cli.parameter_binder import ParameterBinder
        from pirlo.infrastructure.adapters.cli.parameter_snapshot_writer import (
            ParameterSnapshotWriter,
        )
        from pirlo.infrastructure.adapters.orchestrator.factory import (
            OrchestratorFactory,
        )
        from pirlo.infrastructure.services.run_preparer import RunPreparer

        resolved_playbook_name = (
            playbook_name
            or getattr(cls, "playbook_name", None)
            or cls.__name__.lower().replace("session", "")
        )

        raw_arguments: list[str] = extract_raw_arguments_excluding_command(
            sys.argv, resolved_playbook_name
        )
        playbook_invocation: PlaybookInvocation = PlaybookInvocation.from_raw(
            raw_arguments, default_orchestrator_name="prefect"
        )

        if not playbook_invocation.orchestrator_args:
            print("No orchestrator engine specified after '--'.", file=sys.stderr)
            sys.exit(1)

        orchestrator_name: str = playbook_invocation.orchestrator_args[0]
        pirlo_workspace: Path = get_workspace_path()

        # Step A: Prepare pure data run spec
        argument_parser_builder: ArgumentParserBuilder = ArgumentParserBuilder(cls.play)
        playbook_parser: argparse.ArgumentParser = argument_parser_builder.build_parser(
            resolved_playbook_name
        )

        parameter_resolver: ParameterResolver = ParameterResolver.create(
            playbook_parser=playbook_parser,
            playbook_invocation=playbook_invocation,
            pirlo_workspace=pirlo_workspace,
            toml_config={},
        )

        preparer: RunPreparer = RunPreparer(
            playbook_cls=cls,
            pirlo_workspace=pirlo_workspace,
            parameter_resolver=parameter_resolver,
        )
        prepared_run: PreparedRun = preparer.prepare(
            playbook_name=resolved_playbook_name,
            playbook_invocation=playbook_invocation,
        )

        # Step B: Instantiate orchestrator engine service directly via OrchestratorFactory
        orchestrator: TaskOrchestrator = OrchestratorFactory.create_from_invocation(
            name=orchestrator_name,
            playbook_name=resolved_playbook_name,
            orchestrator_flags=playbook_invocation.orchestrator_args,
        )

        # Step C: Instantiate pitch with injected prepared_run
        terminal_pitch: TerminalPitch = cls(
            prepared_run=prepared_run,
        )

        parameter_provider: ParameterProvider = ParameterProvider(parameter_resolver)
        parameter_snapshot_writer: ParameterSnapshotWriter = ParameterSnapshotWriter(
            parameter_provider
        )

        bound_pitch: TerminalPitch = ParameterBinder.bind_values(
            terminal_pitch, prepared_run.parameters
        )
        bound_pitch.orchestrator = orchestrator
        parameter_snapshot_writer.write(bound_pitch, prepared_run.parameter_file_path)

        async def _play() -> RunResult[Any]:
            run_result: RunResult[Any] = await bound_pitch.play(**prepared_run.parameters)
            bound_pitch.goal(
                message=f"Run '{prepared_run.run_id}' completed!",
                detail=f"Result:\n{ run_result.data}",
            )
            return run_result

        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_play())
        else:
            if loop.is_running():
                return _play()  # type: ignore[return-value]
            else:
                return loop.run_until_complete(_play())

    # --- Concrete Port Implementations ---

    def header(self, title: str, subtitle: str | None = None) -> None:
        text = f"[bold green]{title}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self._console.print(Panel(text, expand=False, border_style="cyan"))

    def status(self, message: str) -> Status:
        return self._console.status(
            f"[bold green]{message}[/bold green]", spinner="dots"
        )

    def lineup(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
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

    def goal(self, message: str, detail: str | None = None) -> None:
        text = f"⚽[bold green]GOAL! {message}[/bold green] "
        if detail:
            text += f"\n[cyan]{detail}[/cyan]"
        self._console.print(Panel(text, border_style="green", expand=False))

    def red_card(self, message: str, detail: str | None = None) -> None:
        text = f"🟥 [bold red]RED CARD! {message}[/bold red] "
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self._console.print(Panel(text, border_style="red", expand=False))

    def yellow_card(self, message: Any, detail: str | None = None) -> None:
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
