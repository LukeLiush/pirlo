# src/pirlo/core/ports/play.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.ports.playbook_ui import PlaybookUI
from pirlo.infrastructure.adapters.cli.terminal_playbook_ui import TerminalPlaybookUI


class RequireDescriptor[OutputT]:
    """Declares an upstream play dependency on a Play class."""

    def __init__(self, play_cls: type[Play[OutputT]], **kwargs: Any) -> None:
        self.play_cls: type[Play[OutputT]] = play_cls
        self.kwargs: dict[str, Any] = kwargs
        self.attr_name: str = ""

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.attr_name = name

    def __get__(self, instance: Any, owner: type[Any]) -> OutputT:
        if instance is None:
            return self  # type: ignore[return-value]
        # Injected at runtime by the orchestrator / task runner
        return instance.__dict__.get(self.attr_name)  # type: ignore[no-any-return]


def requires[OutputT](play_cls: type[Play[OutputT]], **kwargs: Any) -> OutputT:
    """Declaratively requires an upstream play output."""
    return RequireDescriptor(play_cls, **kwargs)  # type: ignore[return-value]


class Play[OutputT](ABC):
    """Atomic tactical unit of execution containing pure business logic."""

    def __init__(self, ui: PlaybookUI | None = None) -> None:
        self._ui: PlaybookUI = ui if ui is not None else TerminalPlaybookUI()

    @property
    def ui(self) -> PlaybookUI:
        """Interactive terminal telemetry reporting commentary, goals, and headers."""
        return self._ui

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> OutputT:
        """Execute the play logic and return typed output."""
        raise NotImplementedError

    @classmethod
    def get_upstream_requirements(cls) -> dict[str, RequireDescriptor[Any]]:
        """Discovers all requires(...) descriptors declared on this play."""
        requirements: dict[str, RequireDescriptor[Any]] = {}
        for base in reversed(cls.__mro__):
            for key, value in base.__dict__.items():
                if isinstance(value, RequireDescriptor):
                    requirements[key] = value
        return requirements

    @classmethod
    async def run_play(cls, **kwargs: Any) -> OutputT:
        """Executes the Play and all its upstream dependencies via Prefect in ephemeral mode."""
        from typing import cast

        from pirlo.core.services.blueprint_extractor import BlueprintExtractor
        from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
            PrefectCompiler,
        )

        blueprint = BlueprintExtractor.extract_from_play(cls, user_kwargs=kwargs)
        res = await PrefectCompiler.run_ephemeral(blueprint)
        return cast(OutputT, res)

    def extract_blueprint(self, **kwargs: Any) -> Any:
        """Extracts the PlaybookBlueprint IR for this Play and its upstream requirements."""
        from pirlo.core.services.blueprint_extractor import BlueprintExtractor

        return BlueprintExtractor.extract_from_play(self.__class__, user_kwargs=kwargs)

    @classmethod
    def cli(cls, playbook_name: str | None = None) -> Any:
        """Parse CLI parameters using POSIX '--' delimiter and execute the play."""
        from pirlo.infrastructure.adapters.cli.cli_playbook_runner import (
            CliPlaybookRunner,
        )

        return CliPlaybookRunner.run(cls, playbook_name=playbook_name)
