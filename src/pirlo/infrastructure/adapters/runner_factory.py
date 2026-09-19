# src/pirlo/infrastructure/adapters/runner_factory.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pirlo.core.ports.runner import PlayRunner

if TYPE_CHECKING:
    from pirlo.core.models.orchestrator import OrchestratorLink


class PlayRunnerFactory:
    """Factory to retrieve a runner instance by name or orchestrator link."""

    @classmethod
    def get_runner(
        cls,
        runner_name: str = "prefect",
        *,
        orchestrator_name: str | None = None,
        link: OrchestratorLink | None = None,
        **kwargs: Any,
    ) -> PlayRunner:
        from pirlo.core.config import get_workspace_path
        from pirlo.infrastructure.adapters.orchestrator.registry import (
            OrchestratorRegistry,
        )
        from pirlo.infrastructure.adapters.storage.json_orchestrator_repository import (
            JsonOrchestratorRepository,
        )

        resolved_link = link
        if resolved_link is None and orchestrator_name:
            repo = JsonOrchestratorRepository(
                get_workspace_path() / "orchestrators.json"
            )
            resolved_link = repo.get_by_name(orchestrator_name)
            if resolved_link is None:
                raise ValueError(
                    f"Orchestrator link '{orchestrator_name}' not found. "
                    "Run 'pirlo orchestrator list' to view registered connections."
                )

        engine = resolved_link.engine if resolved_link else runner_name
        plugin = OrchestratorRegistry.get(engine)
        return plugin.create_runner(resolved_link, **kwargs)
