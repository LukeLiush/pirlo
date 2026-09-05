# src/pirlo/infrastructure/adapters/orchestrator/prefect_runner.py
from __future__ import annotations

import logging
from typing import Any, Literal

from prefect.settings import (
    PREFECT_API_URL,
    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
    temporary_settings,
)

from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.ports.runner import PlayRunner
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_model import (
    PrefectWorkflow,
)

logger = logging.getLogger(__name__)


class PrefectRunner(PlayRunner[PrefectWorkflow]):
    """Executes a PrefectWorkflow in ephemeral or connected server mode."""

    def __init__(
        self,
        compiler: PrefectCompiler,
        mode: Literal["auto", "ephemeral", "server"] = "auto",
        server_url: str | None = None,
    ) -> None:
        self.compiler: PrefectCompiler = compiler
        self.mode: Literal["auto", "ephemeral", "server"] = mode
        self.server_url: str | None = server_url

    async def run(
        self,
        workflow: PrefectWorkflow,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Executes the compiled PrefectWorkflow model."""
        active_api_url: str | None = self.server_url
        if active_api_url is None and self.mode in ("auto", "server"):
            active_api_url = discover_prefect_server_url()

        if self.mode == "ephemeral" or (self.mode == "auto" and active_api_url is None):
            override_settings: dict[Any, Any] = {
                PREFECT_API_URL: None,
                PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
            }
        else:
            override_settings = {PREFECT_API_URL: active_api_url}

        with temporary_settings(override_settings):
            return await workflow(**kwargs)

    async def run_blueprint(
        self,
        blueprint: PlayBlueprint,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Convenience method to compile and run a PlayBlueprint in one step."""
        workflow: PrefectWorkflow = self.compiler.compile(blueprint)
        return await self.run(workflow, **kwargs)
