# src/pirlo/infrastructure/adapters/orchestrator/prefect_runner.py
from __future__ import annotations

import contextlib
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


class PrefectRunner(PlayRunner):
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
        blueprint: PlayBlueprint,
        **kwargs: Any,
    ) -> PlayOutput | None:
        """Executes the compiled PrefectWorkflow model."""
        workflow: PrefectWorkflow = self.compiler.compile(blueprint)
        active_api_url: str | None = self.server_url
        if active_api_url is None and self.mode in ("auto", "server"):
            active_api_url = discover_prefect_server_url()

        from prefect.settings import (
            PREFECT_LOGGING_EXTRA_LOGGERS,
            PREFECT_LOGGING_LOG_PRINTS,
        )

        if self.mode == "ephemeral" or (self.mode == "auto" and active_api_url is None):
            override_settings: dict[Any, Any] = {
                PREFECT_API_URL: None,
                PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
            }
        else:
            override_settings = {PREFECT_API_URL: active_api_url}

        override_settings[PREFECT_LOGGING_EXTRA_LOGGERS] = ["pirlo"]
        override_settings[PREFECT_LOGGING_LOG_PRINTS] = True

        with temporary_settings(override_settings):
            try:
                res: PlayOutput | None = await workflow(**kwargs)
                return res
            finally:
                with contextlib.suppress(Exception):
                    import inspect

                    from prefect.logging.handlers import APILogWorker

                    drain_res: Any = APILogWorker.drain_all(at_exit=False)
                    if inspect.isawaitable(drain_res):
                        await drain_res

    def get_dashboard_url(self, run_id: str) -> str | None:
        """Constructs Prefect dashboard URL if pirlo connect or a remote Prefect server is active."""
        active_api_url: str | None = self.server_url
        if active_api_url is None and self.mode in ("auto", "server"):
            active_api_url = discover_prefect_server_url()

        if not active_api_url:
            return None

        web_url = active_api_url.removesuffix("/api").rstrip("/")
        return f"{web_url}/flow-runs?name={run_id}"
