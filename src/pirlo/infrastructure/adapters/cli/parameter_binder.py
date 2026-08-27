"""Discover, resolve, and apply playbook parameter values."""

from __future__ import annotations

from typing import Any, TypeVar

from pirlo.infrastructure.services.parameter_provider import ParameterProvider

T = TypeVar("T")


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
    """Applies resolved parameter values onto an instance or dictionary."""

    def __init__(self, provider: ParameterProvider) -> None:
        self._provider = provider

    def bind(self, instance: T) -> T:
        bound = instance
        for name, value in self._provider.provide(type(instance)).items():
            setattr(bound, name, value)
        return bound

    @staticmethod
    def bind_values(instance: T, values: dict[str, Any]) -> T:
        """Applies a dictionary of already-resolved values onto an instance."""
        for name, value in values.items():
            setattr(instance, name, value)
        return instance
