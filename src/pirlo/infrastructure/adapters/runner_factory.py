# src/pirlo/infrastructure/adapters/runner_factory.py
from __future__ import annotations

from pirlo.core.ports.runner import PlayRunner


class PlayRunnerFactory:
    """Factory returning the runner that executes play blueprints."""

    @classmethod
    def get_runner(cls) -> PlayRunner:
        from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
            PrefectRunner,
        )
        from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
            resolve_default_target,
        )

        return PrefectRunner(target=resolve_default_target())
