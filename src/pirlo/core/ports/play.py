# src/pirlo/core/ports/play.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger(__name__)

from pirlo.core.models.blueprint import ParameterValue, ProxyRef, ScalarValue
from pirlo.core.ports.play_ui import PlayUI

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput


class MappedParameter:
    """Wrapper marking a parameter for dynamic subtask fan-in mapping."""

    def __init__(self, target: ProxyRef | list[ScalarValue]) -> None:
        self.target: ProxyRef | list[ScalarValue] = target


def each(target: ProxyRef | list[ScalarValue]) -> MappedParameter:
    """Marks a parameter for dynamic subtask fan-in mapping across items."""
    return MappedParameter(target)


class RequireDescriptor[OutputT]:
    """Declares an upstream play dependency directly within a Play class."""

    def __init__(
        self,
        play_cls: type[Play[OutputT]],
        each: str | None = None,
        field: str | None = None,
        **kwargs: ParameterValue | MappedParameter,
    ) -> None:
        self.play_cls: type[Play[OutputT]] = play_cls
        self.each: str | None = each
        self.field: str | None = field
        self.kwargs: dict[str, ParameterValue | MappedParameter] = kwargs
        self.attr_name: str = ""

    def __set_name__(self, owner: type[object], name: str) -> None:
        self.attr_name = name

    def __get__(self, instance: object | None, owner: type[object]) -> Any:
        if instance is None:
            return self
        return instance.__dict__.get(self.attr_name)


def requires[OutputT](
    play_cls: type[Play[OutputT]],
    each: str | None = None,
    field: str | None = None,
    **kwargs: ParameterValue | MappedParameter,
) -> Any:
    """Declaratively declares an upstream Play dependency inside a Play class."""
    return RequireDescriptor(play_cls, each=each, field=field, **kwargs)


class Play[OutputT](ABC):
    """Atomic tactical unit of execution containing pure business logic."""

    def __init__(
        self,
        ui: PlayUI | None = None,
        play_id: str | None = None,
    ) -> None:
        if ui is None:
            from pirlo.infrastructure.adapters.cli.terminal_play_ui import (
                TerminalPlayUI,
            )

            self._ui: PlayUI = TerminalPlayUI()
        else:
            self._ui = ui
        self._play_id: str | None = play_id

    @property
    def ui(self) -> PlayUI:
        """Interactive terminal telemetry reporting commentary, goals, and headers."""
        return self._ui

    @property
    def play_id(self) -> str | None:
        """Deterministic content-addressed idempotency ID for this execution instance."""
        return self._play_id

    @property
    def logger(self) -> logging.Logger:
        """Structured logger pre-bound to this play's identity hierarchy."""
        play_name = getattr(self, "play_name", None) or self.__class__.__name__
        return logging.getLogger(f"pirlo.play.{play_name}")

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> OutputT:
        """Execute the play logic and return typed output."""
        raise NotImplementedError

    @classmethod
    def get_upstream_requirements(
        cls,
    ) -> dict[str, RequireDescriptor[Any]]:
        """Discovers all requires(...) descriptors declared on this play class."""
        requirements: dict[str, RequireDescriptor[Any]] = {}
        for base in reversed(cls.__mro__):
            for key, value in base.__dict__.items():
                if isinstance(value, RequireDescriptor):
                    requirements[key] = value
        return requirements

    @classmethod
    async def run_play(
        cls,
        runner: str = "prefect",
        **kwargs: ParameterValue,
    ) -> OutputT:
        """Executes the Play and all upstream dependencies via the specified runner."""

        from pirlo.core.ports.runner import PlayRunner
        from pirlo.core.services.blueprint_extractor import BlueprintExtractor
        from pirlo.infrastructure.adapters.runner_factory import (
            PlayRunnerFactory,
        )

        blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
            cls, user_kwargs=kwargs
        )
        play_runner: PlayRunner = PlayRunnerFactory.get_runner(runner)
        raw_result: PlayOutput | None = await play_runner.run(blueprint)
        return cast(OutputT, raw_result)

    def extract_blueprint(
        self, user_kwargs: dict[str, ParameterValue] | None = None
    ) -> PlayBlueprint:
        """Extracts the PlayBlueprint IR for this Play and its upstream requirements."""
        from pirlo.core.services.blueprint_extractor import BlueprintExtractor

        return BlueprintExtractor.extract_from_play(
            self.__class__, user_kwargs=user_kwargs
        )

    @classmethod
    def cli(cls, play_name: str | None = None) -> Any:
        """Parse CLI parameters and execute the play."""
        from pirlo.infrastructure.adapters.cli.cli_play_runner import (
            CliPlayRunner,
        )

        return CliPlayRunner.run(cls, play_name=play_name)
