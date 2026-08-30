from pirlo.core.models.serve_manifest import ActiveSession
from pirlo.core.ports.health_checker import (
    CompositeHealthChecker,
    HealthStatus,
    ServiceHealthChecker,
)


class MockHealthyChecker(ServiceHealthChecker):
    @property
    def service_name(self) -> str:
        return "mock_healthy"

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        return HealthStatus(
            is_healthy=True, service_name=self.service_name, message="Mock is healthy"
        )


class MockUnhealthyChecker(ServiceHealthChecker):
    @property
    def service_name(self) -> str:
        return "mock_unhealthy"

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        return HealthStatus(
            is_healthy=False,
            service_name=self.service_name,
            message="Mock is unhealthy",
        )


def test_composite_health_checker():
    session = ActiveSession(
        remote_host="localhost",
        local_prefect_port=4200,
        local_ollama_port=11434,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
    )

    healthy_composite = CompositeHealthChecker([MockHealthyChecker()])
    status = healthy_composite.check_health(session)
    assert status.is_healthy
    assert "[PASS] Mock_healthy: Mock is healthy" in status.message

    mixed_composite = CompositeHealthChecker(
        [MockHealthyChecker(), MockUnhealthyChecker()]
    )
    mixed_status = mixed_composite.check_health(session)
    assert not mixed_status.is_healthy
    assert "[FAIL] Mock_unhealthy: Mock is unhealthy" in mixed_status.message
