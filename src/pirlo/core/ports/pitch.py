from abc import ABC, abstractmethod
from typing import Any

from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.core.ports.pitch_ui import PitchUI


class Pitch(ABC):
    """Pure Abstract Port representing presentation canvas & lifecycle contract."""

    def __init__(
        self,
        prepared_run: PreparedRun | None = None,
        orchestrator: TaskOrchestrator | None = None,
        ui: PitchUI | None = None,
    ) -> None:
        self._prepared_run = prepared_run
        self._orchestrator = orchestrator
        self._ui = ui

    @property
    def ui(self) -> PitchUI:
        if self._ui is None:
            from pirlo.infrastructure.adapters.cli.terminal_pitch_ui import (
                TerminalPitchUI,
            )

            self._ui = TerminalPitchUI()
        return self._ui

    @property
    def orchestrator(self) -> TaskOrchestrator:
        if self._orchestrator is None:
            raise RuntimeError(
                "Pitch orchestrator has not been initialized. "
                "Ensure Pitch is instantiated with an orchestrator engine."
            )
        return self._orchestrator

    async def prepared_run(self) -> PreparedRun:
        if self._prepared_run is None:
            raise RuntimeError(
                "Pitch prepared_run accessed before preparation. "
                "Ensure RunPreparer has prepared the run before accessing."
            )
        return self._prepared_run

    @abstractmethod
    async def play(self, *args: Any, **kwargs: Any) -> RunResult[Any]:
        """Core playbook execution logic implemented by subclasses."""

    # --- Runner Entrypoints (Lazy Infrastructure Delegation) ---

    @classmethod
    def cli(cls, playbook_name: str | None = None) -> RunResult[Any]:
        """Parse CLI parameters using POSIX '--' delimiter and play the pitch."""
        from pirlo.infrastructure.adapters.cli.cli_pitch_runner import (
            CliPitchRunner,
        )

        return CliPitchRunner.run(cls, playbook_name=playbook_name)
