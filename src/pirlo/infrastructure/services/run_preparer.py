"""Prepare a playbook run: resolve params, establish identity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pirlo.core.models.play_invocation import PlayInvocation
from pirlo.core.models.run import PreparedRun
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver
from pirlo.infrastructure.services.run_id_generator import IdentityFactory


class RunPreparer:
    """Turns a raw invocation into a :class:`PreparedRun`."""

    def __init__(
        self,
        parameters: list[dict[str, Any]],
        pirlo_workspace: Path,
        parameter_resolver: ParameterResolver,
    ) -> None:
        """``parameters`` must be the list the CLI parser was built from
        (``ArgumentParserBuilder.parameters``), so every flag in --help is resolved."""
        self._parameters = parameters
        self._pirlo_workspace = pirlo_workspace
        self._parameter_resolver = parameter_resolver

    def prepare(
        self,
        playbook_name: str,
        playbook_invocation: PlayInvocation | None = None,
        toml_config: dict[str, Any] | None = None,
    ) -> PreparedRun:
        resolved_params: dict[str, Any] = self._parameter_resolver.resolve_all(
            self._parameters
        )
        run_name, run_id = self._establish_identity(playbook_name, resolved_params)

        return PreparedRun(
            playbook_name=playbook_name,
            run_name=run_name,
            run_id=run_id,
            workspace=self._pirlo_workspace,
            parameters=resolved_params,
        )

    # --- identity ---------------------------------------------------------

    @staticmethod
    def _establish_identity(
        playbook_name: str, parameters: dict[str, Any]
    ) -> tuple[str, str]:
        identity = IdentityFactory(playbook_name, parameters)
        run_name = identity.generate_run_name()
        run_id = identity.generate_run_id()
        return run_name, run_id
