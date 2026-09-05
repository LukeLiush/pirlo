from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, cast

from pirlo.core.config import get_workspace_path
from pirlo.core.models.playbook_invocation import PlaybookInvocation
from pirlo.core.models.run import PreparedRun, RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.core.ports.play import Play
from pirlo.core.ports.playbook import Playbook
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.cli.terminal_playbook_ui import TerminalPlaybookUI
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


class CliPlaybookRunner:
    """CLI Execution Runner adapter that parses POSIX arguments and runs a Playbook class."""

    @classmethod
    def run(
        cls,
        playbook_cls: type[Playbook | Play[Any]],
        playbook_name: str | None = None,
    ) -> RunResult[Any]:
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
            or getattr(playbook_cls, "playbook_name", None)
            or playbook_cls.__name__.lower().replace("session", "")
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
        argument_parser_builder: ArgumentParserBuilder = ArgumentParserBuilder(
            playbook_cls
        )
        epilog_text = (
            "Orchestrator Options:\n"
            "  Pirlo uses '--' to pass flags to the execution orchestrator engine.\n"
            "  Available orchestrator engines: prefect (default)\n\n"
            "  To view orchestrator engine options:\n"
            f"    pirlo {resolved_playbook_name} -- prefect --help\n\n"
            "  To pass orchestrator options (e.g. schedule, work pool):\n"
            f"    pirlo {resolved_playbook_name} -- prefect -s daily"
        )
        playbook_parser: argparse.ArgumentParser = argument_parser_builder.build_parser(
            resolved_playbook_name, epilog_text=epilog_text
        )

        parameter_resolver: ParameterResolver = ParameterResolver.create(
            playbook_parser=playbook_parser,
            playbook_invocation=playbook_invocation,
            pirlo_workspace=pirlo_workspace,
            toml_config={},
        )

        preparer: RunPreparer = RunPreparer(
            playbook_cls=playbook_cls,
            pirlo_workspace=pirlo_workspace,
            parameter_resolver=parameter_resolver,
        )
        prepared_run: PreparedRun = preparer.prepare(
            playbook_name=resolved_playbook_name,
            playbook_invocation=playbook_invocation,
        )

        from pirlo.core.ports.play import Play

        is_play_cls = issubclass(playbook_cls, Play)
        if is_play_cls:
            play_instance = playbook_cls(ui=TerminalPlaybookUI())
            bound_playbook = None
        else:
            # Step B (Legacy Playbook): Instantiate orchestrator engine service directly via OrchestratorFactory
            orchestrator: TaskOrchestrator = OrchestratorFactory.create_from_invocation(
                name=orchestrator_name,
                playbook_name=resolved_playbook_name,
                orchestrator_flags=playbook_invocation.orchestrator_args,
            )

            # Step C: Instantiate playbook with injected TerminalPlaybookUI and orchestrator
            legacy_cls = cast(type[Playbook[Any]], playbook_cls)
            playbook_instance: Playbook[Any] = legacy_cls(
                prepared_run=prepared_run,
                orchestrator=orchestrator,
                ui=TerminalPlaybookUI(),
            )

            parameter_provider: ParameterProvider = ParameterProvider(
                parameter_resolver
            )
            parameter_snapshot_writer: ParameterSnapshotWriter = (
                ParameterSnapshotWriter(parameter_provider)
            )

            bound_playbook = ParameterBinder.bind_values(
                playbook_instance, prepared_run.parameters
            )

            parameter_snapshot_writer.write(
                bound_playbook, prepared_run.parameter_file_path
            )

        async def _play() -> RunResult[Any]:
            if is_play_cls:
                from pirlo.core.services.blueprint_extractor import BlueprintExtractor
                from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
                    PrefectCompiler,
                )

                blueprint = BlueprintExtractor.extract_from_play(
                    cast(type[Play[Any]], playbook_cls),
                    user_kwargs=prepared_run.parameters,
                )
                raw_result: Any = await PrefectCompiler.run_ephemeral(blueprint)
                active_ui = play_instance.ui
            else:
                assert bound_playbook is not None
                raw_result = await bound_playbook.run_play(**prepared_run.parameters)
                active_ui = bound_playbook.ui

            if isinstance(raw_result, RunResult):
                final_run_result: RunResult[Any] = raw_result
            else:
                final_run_result = RunResult(
                    run_id=prepared_run.run_id,
                    status=RunStatus.COMPLETED,
                    data=raw_result,
                )

            active_ui.goal(
                message=f"Run '{prepared_run.run_id}' completed!",
                detail=f"Result:\n{final_run_result.data}",
            )
            return final_run_result

        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_play())
        else:
            if loop.is_running():
                return _play()  # type: ignore[return-value]
            else:
                return loop.run_until_complete(_play())
