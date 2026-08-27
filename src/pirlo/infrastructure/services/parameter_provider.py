from typing import Any

from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    extract_signature_parameters,
)
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver


def discover_parameters(target_cls_or_fn: Any) -> list[dict[str, Any]]:
    """Collect parameter metadata dicts declared on a playbook/orchestrator signature."""
    if hasattr(target_cls_or_fn, "play"):
        return extract_signature_parameters(target_cls_or_fn.play)
    if hasattr(target_cls_or_fn, "execute"):
        return extract_signature_parameters(target_cls_or_fn.execute)
    return extract_signature_parameters(target_cls_or_fn)


class ParameterProvider:
    """Discovers and resolves parameter values for a playbook or orchestrator class."""

    def __init__(self, parameter_resolver: ParameterResolver) -> None:
        self._parameter_resolver = parameter_resolver

    def provide(self, target_cls_or_fn: Any) -> dict[str, Any]:
        parameters = discover_parameters(target_cls_or_fn)
        return self._parameter_resolver.resolve_all(parameters)
