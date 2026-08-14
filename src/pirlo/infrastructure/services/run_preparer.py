"""Prepare a playbook run: select orchestrator, resolve params, establish identity."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pirlo.core.models.parameters import Parameter, Parameterizable
from pirlo.core.models.playbook_invocation import PlaybookInvocation
from pirlo.core.models.run import PreparedRun
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
from pirlo.infrastructure.services.parameter_provider import discover_parameters
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver
from pirlo.infrastructure.services.run_id_generator import IdentityFactory


class RunPreparer:
    """Turns a raw invocation into a :class:`PreparedRun`.

    Sequences three concerns — orchestrator selection, parameter resolution,
    and run-identity generation — so ``cli`` receives a single ready-to-use
    value object without wiring the pieces itself.
    """

    def __init__(
            self,
            parameterizable_class: type[Parameterizable],
            pirlo_workspace: Path,
    ) -> None:
        self._parameterizable_class = parameterizable_class
        self._pirlo_workspace = pirlo_workspace
        self._parser_builder = ArgumentParserBuilder(parameterizable_class)

    def prepare(
            self,
            playbook_name: str,
            playbook_invocation: PlaybookInvocation,
            toml_config: dict[str, Any] | None = None,
    ) -> PreparedRun:
        parameters: dict[str, Any] = self._resolve_parameters(
            playbook_name, playbook_invocation, toml_config
        )
        run_name: str
        run_id: str
        run_name, run_id = self._establish_identity(playbook_name, parameters)

        return PreparedRun(
            playbook_name=playbook_name,
            run_name=run_name,
            run_id=run_id,
            workspace=self._pirlo_workspace,
            parameters=parameters,
        )

    # --- parameter resolution --------------------------------------------

    def _resolve_parameters(
            self,
            playbook_name: str,
            playbook_invocation: PlaybookInvocation,
            toml_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        parser = self._parser_builder.build_parser(
            playbook_name=playbook_name,
        )
        resolver = ParameterResolver.create(
            parser,
            playbook_invocation,
            self._pirlo_workspace,
            toml_config or {},
        )
        parameters: list[Parameter] = discover_parameters(self._parameterizable_class)
        return resolver.resolve_all(parameters)

    # --- identity ---------------------------------------------------------

    @staticmethod
    def _establish_identity(
            playbook_name: str, parameters: dict[str, Any]
    ) -> tuple[str, str]:
        identity = IdentityFactory(playbook_name, parameters)
        run_name = identity.generate_run_name()
        run_id = identity.generate_run_id()
        return run_name, run_id
