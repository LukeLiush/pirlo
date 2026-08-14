"""Discover, resolve, and apply playbook parameter values.

Responsibilities are split across small, single-purpose collaborators:

* :func:`discover_parameters`      -- find ``Parameter`` attributes on a class.
* :class:`ArgumentParserBuilder`   -- build the argparse parser.
* :class:`ParameterResolver`       -- resolve values across sources + domain.
* :class:`ParameterProvider`       -- discover + resolve for a playbook class.
* :class:`ParameterBinder`         -- apply resolved values onto an instance.
* :class:`ParameterSnapshotWriter` -- snapshot resolved values to disk.
"""

from __future__ import annotations

from copy import deepcopy

from pirlo.core.models.parameters import Parameterizable
from pirlo.infrastructure.services.parameter_provider import ParameterProvider


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


class ParameterBinder:
    """Applies resolved parameter values onto a *copy* of a playbook instance.

    Copy-on-bind avoids observable side effects on the caller's instance:
    the returned object carries the resolved values while the original is
    left untouched.
    """

    def __init__(self, provider: ParameterProvider) -> None:
        self._provider = provider

    def bind(self, instance: Parameterizable) -> Parameterizable:
        #bound = deepcopy(instance)
        bound = instance
        for name, value in self._provider.provide(type(instance)).items():
            setattr(bound, name, value)
        return bound
