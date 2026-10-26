# pirlo/infrastructure/adapters/orchestrator/prefect_settings.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prefect.settings import (
    PREFECT_API_URL,
    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
)

from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)


@dataclass(frozen=True)
class PrefectServerSettings:
    """Resolved Prefect connection settings for a run.

    Encapsulates server-URL discovery, /api normalization, and the
    ephemeral-vs-server override dictionary handed to temporary_settings().
    """

    api_url: str | None

    @classmethod
    def resolve(cls, configured_url: str | None) -> PrefectServerSettings:
        api_url = configured_url or discover_prefect_server_url()
        if api_url:
            api_url = api_url.rstrip("/")
            if not api_url.endswith("/api"):
                api_url = f"{api_url}/api"
        return cls(api_url=api_url)

    @property
    def is_server_mode(self) -> bool:
        return self.api_url is not None

    @property
    def web_ui_base(self) -> str | None:
        if not self.api_url:
            return None
        return self.api_url.rstrip("/").removesuffix("/api")

    @property
    def overrides(self) -> dict[Any, Any]:
        if self.api_url:
            return {PREFECT_API_URL: self.api_url}
        return {
            PREFECT_API_URL: None,
            PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
        }
