from abc import ABC
from collections.abc import Callable
from typing import Any


class Parameterizable(ABC):
    """A playbook-like class that declares ``Parameter`` attributes.

    Structural contract for anything the parser/resolver can introspect
    for its parameters. Implementers simply declare ``Parameter`` instances
    as class attributes; no base class or registration required.
    """

    # Marker protocol: the contract is "has Parameter class attributes",
    # which is discovered dynamically rather than via a fixed attribute.


class Parameter:
    """Descriptor class for defining CLI parameters on a Pitch."""

    def __init__(
        self,
        type_func: Callable,
        default: Any = None,
        help: str | None = None,
        short: str | None = None,
        env_name: str | list[str] | None = None,
    ):
        self.type_func = type_func
        self.default = default
        self.help = help
        self.short = short
        self.env_name = env_name
        self.name: str = ""

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get(self.name, self.default)

    def __set__(self, instance, value):
        if instance is not None and self.name is not None:
            instance.__dict__[self.name] = value


class LinkParameter(Parameter):
    """Descriptor class for defining CLI parameters that resolve to an LlmLink object."""

    def __init__(
        self,
        default: Any = None,
        help: str | None = None,
        short: str | None = None,
        env_name: str | list[str] | None = None,
    ):
        super().__init__(
            type_func=str,
            default=default,
            help=help,
            short=short,
            env_name=env_name,
        )
