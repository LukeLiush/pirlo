import json
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from pirlo.core.models.serve_manifest import ActiveSession


@dataclass(frozen=True)
class HealthStatus:
    is_healthy: bool
    service_name: str
    message: str


class ServiceHealthChecker(ABC):
    """Abstract Strategy Port for service health verification."""

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Name of the service (e.g. 'prefect', 'ollama')."""

    @abstractmethod
    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        """Verify service health using the domain session."""


class PrefectHealthChecker(ServiceHealthChecker):
    @property
    def service_name(self) -> str:
        return "prefect"

    @staticmethod
    def check_url(url: str, timeout_seconds: float = 0.3) -> bool:
        """Fast endpoint health probe for any Prefect server API URL."""
        endpoint = f"{url.rstrip('/')}/health"
        try:
            res = httpx.get(endpoint, timeout=timeout_seconds)
            return res.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        if self.check_url(session.prefect_api_url, timeout_seconds=timeout_seconds):
            return HealthStatus(
                is_healthy=True,
                service_name=self.service_name,
                message="Prefect API is healthy",
            )
        return HealthStatus(
            is_healthy=False,
            service_name=self.service_name,
            message="Prefect API is unreachable or unhealthy",
        )


class OllamaHealthChecker(ServiceHealthChecker):
    @property
    def service_name(self) -> str:
        return "ollama"

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        root_url = session.ollama_base_url.replace("/v1", "").rstrip("/")
        endpoint = f"{root_url}/api/version"
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "Pirlo/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    version = data.get("version", "unknown")
                    return HealthStatus(
                        is_healthy=True,
                        service_name=self.service_name,
                        message=f"Ollama v{version} active",
                    )
                return HealthStatus(
                    is_healthy=False,
                    service_name=self.service_name,
                    message=f"HTTP {resp.status}",
                )
        except Exception as e:  # noqa: BLE001
            return HealthStatus(
                is_healthy=False,
                service_name=self.service_name,
                message=f"Unreachable: {e}",
            )


class CompositeHealthChecker(ServiceHealthChecker):
    """GoF Composite Pattern: Groups multiple ServiceHealthCheckers into a single pipeline."""

    def __init__(self, checkers: list[ServiceHealthChecker] | None = None) -> None:
        self._checkers: list[ServiceHealthChecker] = checkers or []

    @property
    def service_name(self) -> str:
        return "composite"

    def add(self, checker: ServiceHealthChecker) -> "CompositeHealthChecker":
        self._checkers.append(checker)
        return self

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        all_messages: list[str] = []
        is_healthy: bool = True

        for checker in self._checkers:
            status = checker.check_health(session, timeout_seconds=timeout_seconds)
            prefix = "[PASS]" if status.is_healthy else "[FAIL]"
            all_messages.append(
                f"{prefix} {status.service_name.capitalize()}: {status.message}"
            )
            if not status.is_healthy:
                is_healthy = False

        return HealthStatus(
            is_healthy=is_healthy,
            service_name="composite",
            message="\n".join(all_messages),
        )
