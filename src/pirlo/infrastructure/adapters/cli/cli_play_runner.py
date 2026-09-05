# src/pirlo/infrastructure/adapters/cli/cli_play_runner.py
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from pirlo.core.config import get_workspace_path
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.models.play_invocation import PlayInvocation
from pirlo.core.models.run import PreparedRun, RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.play import Play
from pirlo.core.ports.runner import PlayRunner
from pirlo.core.services.blueprint_extractor import BlueprintExtractor
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.cli.terminal_play_ui import TerminalPlayUI
from pirlo.infrastructure.adapters.runner_factory import (
    PlayRunnerFactory,
)
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver
from pirlo.infrastructure.services.run_preparer import RunPreparer


def extract_raw_arguments_excluding_command(
    sys_argv: list[str], play_name: str
) -> list[str]:
    """Strips binary and play command names from sys.argv."""
    raw_args = sys_argv[1:]
    if raw_args and raw_args[0] == play_name:
        raw_args = raw_args[1:]
    return raw_args


class CliPlayRunner:
    """CLI Execution Runner adapter that parses POSIX arguments and runs a Play class."""

    @classmethod
    def run(
        cls,
        play_cls: type[Play[Any]],
        play_name: str | None = None,
    ) -> RunResult[Any]:
        """Parse CLI parameters using the POSIX '--' delimiter and execute the play."""
        resolved_play_name: str | None = play_name or getattr(
            play_cls, "play_name", None
        )
        if resolved_play_name is None:
            raise ValueError(
                f"Play class {play_cls} does not have a @play name attribute."
            )

        raw_arguments: list[str] = extract_raw_arguments_excluding_command(
            sys.argv, resolved_play_name
        )
        play_invocation: PlayInvocation = PlayInvocation.from_raw(
            raw_arguments, default_orchestrator_name="prefect"
        )

        pirlo_workspace: Path = get_workspace_path()

        # Step A: Build play parser with bubbled upstream parameters
        argument_parser_builder: ArgumentParserBuilder = ArgumentParserBuilder(play_cls)
        play_parser: argparse.ArgumentParser = argument_parser_builder.build_parser(
            resolved_play_name
        )

        parameter_resolver: ParameterResolver = ParameterResolver.create(
            playbook_parser=play_parser,
            playbook_invocation=play_invocation,
            pirlo_workspace=pirlo_workspace,
            toml_config={},
        )

        preparer: RunPreparer = RunPreparer(
            playbook_cls=play_cls,
            pirlo_workspace=pirlo_workspace,
            parameter_resolver=parameter_resolver,
        )
        prepared_run: PreparedRun = preparer.prepare(
            playbook_name=resolved_play_name,
            playbook_invocation=play_invocation,
        )

        # Step B: Instantiate play with injected TerminalPlayUI
        play_instance: Play[Any] = play_cls(ui=TerminalPlayUI())

        runner_name: str = (
            play_invocation.orchestrator_args[0]
            if play_invocation.orchestrator_args
            else "prefect"
        )
        runner_instance: PlayRunner[PlayBlueprint] = (
            PlayRunnerFactory.get_runner(runner_name)
        )

        async def _play() -> RunResult[Any]:
            blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
                play_cls,
                user_kwargs=prepared_run.parameters,
            )
            raw_result: PlayOutput | None = await runner_instance.run(blueprint)

            if isinstance(raw_result, RunResult):
                final_run_result: RunResult[Any] = raw_result
            else:
                final_run_result = RunResult(
                    run_id=prepared_run.run_id,
                    status=RunStatus.COMPLETED,
                    data=raw_result,
                )

            play_instance.ui.goal(
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


# Backward-compatibility alias
CliPlaybookRunner = CliPlayRunner
