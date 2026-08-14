from typing import Any

from pirlo.core.models.parameters import Parameter, Parameterizable
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver


# --- discovery -----------------------------------------------------------
#
# A stateless free function: it holds no state and needs no configuration,
# so a class or injected instance would be ceremony with no benefit. Reads
# from the *class*, never an instance, so it stays correct even after values
# have been bound onto an instance.


def discover_parameters(
        parameterizable_class: type[Parameterizable],
) -> list[Parameter]:
    """Collect every ``Parameter`` declared on a playbook class."""
    return [
        attr_val
        for attr_name in dir(parameterizable_class)
        if isinstance(attr_val := getattr(parameterizable_class, attr_name), Parameter)
    ]


# --- provider seam -------------------------------------------------------
#
# Pairs discovery + resolution so downstream consumers (binder, writer)
# don't each repeat "discover then resolve". The single place that knows
# those two steps belong together.


class ParameterProvider:
    """Discovers and resolves the parameter values for a playbook class."""

    def __init__(self, parameter_resolver: ParameterResolver) -> None:
        self._parameter_resolver = parameter_resolver

    def provide(self, parameterizable_class: type[Parameterizable]) -> dict[str, Any]:
        parameters = discover_parameters(parameterizable_class)
        return self._parameter_resolver.resolve_all(parameters)
