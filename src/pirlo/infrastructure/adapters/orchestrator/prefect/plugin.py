from typing import Any

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.decorators import orchestrator
from pirlo.core.models.orchestrator import OrchestratorVerificationResult
from pirlo.core.ports.orchestrator_plugin import OrchestratorPlugin
from pirlo.core.ports.runner import PlayRunner
from pirlo.infrastructure.adapters.orchestrator.prefect.models import PrefectLink
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
    PrefectRunner,
)


@orchestrator(
    name="prefect",
    description="Plugin adapter integrating Prefect 3.x with Pirlo.",
)
class PrefectPlugin(OrchestratorPlugin[PrefectLink]):
    """Plugin adapter integrating Prefect 3.x with Pirlo."""

    def verify(self, link: PrefectLink) -> OrchestratorVerificationResult:
        """Verifies connectivity, authentication, and readiness of the orchestrator link."""
        if link.is_ephemeral:
            return OrchestratorVerificationResult(
                success=True,
                message="Local ephemeral Prefect engine is ready (in-process SQLite).",
                details={"mode": "ephemeral"},
            )

        import httpx

        raw_url = link.server_url.rstrip("/")
        api_url = raw_url if raw_url.endswith("/api") else f"{raw_url}/api"
        endpoint = f"{api_url}/health"
        try:
            res = httpx.get(endpoint, timeout=3.0)
            if res.status_code == 200:
                return OrchestratorVerificationResult(
                    success=True,
                    message=f"Connected to Prefect server at {api_url}",
                    details={
                        "status_code": res.status_code,
                        "work_pool": link.work_pool,
                    },
                )
            return OrchestratorVerificationResult(
                success=False,
                message=f"Prefect server returned status {res.status_code}",
                details={"status_code": res.status_code},
            )
        except Exception as exc:  # noqa: BLE001
            return OrchestratorVerificationResult(
                success=False,
                message=f"Connection failed: {exc}",
                details={"error": str(exc)},
            )

    def create_runner(self, link: PrefectLink | None, **kwargs: Any) -> PlayRunner:
        if link is None or link.is_ephemeral:
            default_mode = "ephemeral"
            default_server_url = None
            default_work_pool = DEFAULT_WORK_POOL
        else:
            default_mode = "server"
            default_server_url = link.server_url
            default_work_pool = link.work_pool

        mode = kwargs.pop("mode", default_mode)
        server_url = kwargs.pop("server_url", default_server_url)
        work_pool = kwargs.pop("work_pool", default_work_pool)
        compiler = kwargs.pop("compiler", None) or PrefectCompiler()

        return PrefectRunner(
            compiler=compiler,
            mode=mode,
            server_url=server_url,
            work_pool=work_pool,
            **kwargs,
        )
