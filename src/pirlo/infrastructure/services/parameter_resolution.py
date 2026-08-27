from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.models.playbook_invocation import PlaybookInvocation
from pirlo.core.ports.link_repository import LinkRepository
from pirlo.infrastructure.adapters.cli.parameter_sources import (
    ArgumentSource,
    EnvironmentSource,
    ParameterSource,
    TomlSource,
    ValueConverter,
)


class MissingLinkError(Exception):
    """Raised when a LinkParameter references a link that doesn't exist."""

    def __init__(self, param_name: str, link_name: str) -> None:
        self.param_name = param_name
        self.link_name = link_name
        super().__init__(
            f"Missing required link '{link_name}' for parameter '{param_name}'"
        )

    @property
    def flag_name(self) -> str:
        """The CLI flag form of the parameter, e.g. ``--my-link``."""
        return f"--{self.param_name.replace('_', '-')}"


class ParameterResolver:
    """Resolves parameter values across sources following precedence:

        CLI argument > Environment variable > pirlo.toml > Default

    then resolves domain-specific parameter types (e.g. ``LinkParameter``)
    into their corresponding domain objects.

    Resolves a *given* list of parameters -- it does not discover them -- so
    it stays decoupled from class introspection and is easy to test with a
    hand-built parameter list.
    """

    def __init__(
        self,
        sources: list[ParameterSource],
        link_repository: LinkRepository,
    ) -> None:
        # Ordered lowest -> highest precedence.
        self._sources = sources
        self._link_repository = link_repository

    # --- factory ----------------------------------------------------------

    @classmethod
    def create(
        cls,
        playbook_parser: argparse.ArgumentParser,
        playbook_invocation: PlaybookInvocation,
        pirlo_workspace: Path,
        toml_config: dict[str, Any] | None = None,
    ) -> ParameterResolver:
        """Wire the default precedence sources and JSON-backed link repo.

        Parses the pre-split ``playbook_invocation.playbook_args`` with the
        supplied parser and assembles the source stack in precedence order.
        """
        from pirlo.infrastructure.adapters.storage.json_link_repository import (
            JsonLinkRepository,
        )

        parsed_args = playbook_parser.parse_args(playbook_invocation.playbook_args)

        converter = ValueConverter()
        sources: list[ParameterSource] = [
            TomlSource(toml_config or {}, converter),
            EnvironmentSource(converter),
            ArgumentSource(parsed_args, converter),
        ]

        links_file = (pirlo_workspace / "links.json").expanduser()
        link_repository: LinkRepository = JsonLinkRepository(links_file)
        return cls(sources, link_repository)

    # --- public API -------------------------------------------------------

    def resolve_all(self, parameters: list[Parameter]) -> dict[str, Any]:
        """Resolve every parameter into a ``{name: value}`` dict."""
        raw_values = self._merge_sources(parameters)
        return {
            param.name: self._resolve_domain_object(param, raw_values[param.name])
            for param in parameters
        }

    # --- precedence resolution --------------------------------------------

    def _merge_sources(self, parameters: list[Parameter]) -> dict[str, Any]:
        """Merge all sources over defaults, honoring precedence order."""
        merged: dict[str, Any] = {p.name: p.default for p in parameters}
        for source in self._sources:  # lowest -> highest precedence
            merged.update(source.bind(parameters))
        return merged

    # --- domain resolution ------------------------------------------------

    def _resolve_domain_object(self, param: Parameter, value: Any) -> Any:
        if not isinstance(param, LinkParameter):
            return value
        if not value:
            return None
        return self._resolve_link(param, value)

    def _resolve_link(self, param: LinkParameter, name: str) -> LlmLink:
        assert self._link_repository is not None
        link_obj = self._link_repository.get_by_name(name)
        if not link_obj:
            raise MissingLinkError(param.name, name)
        return link_obj
