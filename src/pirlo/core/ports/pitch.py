from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


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
        self.name = None

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


from pirlo.core.models.run_result import RunResult


class Pitch(ABC):
    """Pure Abstract Port representing the presentation canvas & lifecycle contract."""

    @property
    @abstractmethod
    def run_name(self) -> str:
        """Deterministic run workload name."""

    @property
    @abstractmethod
    def run_id(self) -> str:
        """Unique execution instance ID."""

    @property
    @abstractmethod
    def domain_options(self) -> dict[str, Any]:
        """Dictionary of domain playbook parameters."""

    @abstractmethod
    async def on_play(self) -> RunResult[Any]:
        """Core playbook execution logic implemented by subclasses."""

    @abstractmethod
    async def play(self) -> RunResult[Any]:
        """Framework template method managing execution lifecycle."""

    @abstractmethod
    def header(self, title: str, subtitle: str | None = None):
        """Draw a banner/header."""

    @abstractmethod
    def status(self, message: str) -> Any:
        """Context manager for loading status (spinner)."""

    @abstractmethod
    def lineup(self, title: str, columns: list[str], rows: list[list[str]]):
        """Draw starting lineup table."""

    @abstractmethod
    async def var_check(self, message: str) -> None:
        """VAR Check: Halts play to pause and wait for the user to press Enter."""

    @abstractmethod
    def goal(self, message: str, detail: str | None = None):
        """Draw success panel (Scoring a goal!)."""

    @abstractmethod
    def red_card(self, message: str, detail: str | None = None):
        """Draw error panel (Red Card!)."""

    @abstractmethod
    def yellow_card(self, message: str, detail: str | None = None):
        """Draw warning panel (Warning flag)."""
