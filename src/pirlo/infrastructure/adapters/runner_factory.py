# src/pirlo/infrastructure/adapters/runner_factory.py
from __future__ import annotations

from typing import Any

from pirlo.core.ports.runner import PlayRunner
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
    PrefectRunner,
)


class PlayRunnerFactory:
    """Factory to retrieve a runner instance by name ('prefect')."""

    @classmethod
    def get_runner(
        cls, runner_name: str = "prefect", **kwargs: Any
    ) -> PlayRunner[Any]:
        normalized_name: str = runner_name.lower().strip()
        if normalized_name == "prefect":
            compiler: PrefectCompiler = (
                kwargs.pop("compiler", None) or PrefectCompiler()
            )
            return PrefectRunner(compiler=compiler, **kwargs)
        raise ValueError(f"Unknown runner engine: '{runner_name}'")
