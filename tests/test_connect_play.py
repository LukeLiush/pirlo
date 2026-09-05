from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pirlo.core.models.serve_manifest import ActiveSession
from pirlo.core.ports.health_checker import HealthStatus
from pirlo.playbooks.connect.main import ConnectSession


@pytest.mark.anyio
async def test_connect_session_playbook_connect_success(tmp_path):
    session = ConnectSession()

    mock_service = MagicMock()
    mock_service.connect.return_value = ActiveSession(
        remote_host="gpu-server.local",
        local_prefect_port=4201,
        local_ollama_port=11435,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
    )

    with (
        patch(
            "pirlo.playbooks.connect.main.ConnectService.create_default",
            return_value=mock_service,
        ),
        patch.object(session, "_monitor_health_loop", new_callable=AsyncMock),
    ):
        result = await session.execute(remote_host="ubuntu@gpu-server.local")
        assert result.status.name == "COMPLETED"
        assert result.data["remote_host"] == "gpu-server.local"
        mock_service.connect.assert_called_once_with(
            remote_host="gpu-server.local", ssh_user="ubuntu", ssh_port=22
        )


@pytest.mark.anyio
async def test_connect_session_playbook_disconnect(tmp_path):
    session = ConnectSession()

    mock_service = MagicMock()

    with patch(
        "pirlo.playbooks.connect.main.ConnectService.create_default",
        return_value=mock_service,
    ):
        result = await session.execute(down=True)
        assert result.status.name == "COMPLETED"
        assert result.data["status"] == "disconnected"
        mock_service.disconnect.assert_called_once()


@pytest.mark.anyio
async def test_connect_session_playbook_status(tmp_path):
    session = ConnectSession()

    mock_service = MagicMock()
    mock_service.get_status.return_value = (
        ActiveSession(
            remote_host="gpu-server.local",
            local_prefect_port=4201,
            local_ollama_port=11435,
            remote_prefect_port=4200,
            remote_ollama_port=11434,
        ),
        HealthStatus(is_healthy=True, service_name="all", message="Healthy"),
    )

    with patch(
        "pirlo.playbooks.connect.main.ConnectService.create_default",
        return_value=mock_service,
    ):
        result = await session.execute(status=True)
        assert result.status.name == "COMPLETED"
        assert result.data["active"]
        assert result.data["remote_host"] == "gpu-server.local"


@pytest.mark.anyio
async def test_connect_session_playbook_circuit_breaker(tmp_path):
    session = ConnectSession()

    mock_service = MagicMock()
    mock_service.connect.return_value = ActiveSession(
        remote_host="gpu-server.local",
        local_prefect_port=4201,
        local_ollama_port=11435,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
    )
    mock_service.health_checker.check_health.return_value = HealthStatus(
        is_healthy=False, service_name="test", message="Degraded"
    )

    with (
        patch(
            "pirlo.playbooks.connect.main.ConnectService.create_default",
            return_value=mock_service,
        ),
        patch("pirlo.playbooks.connect.main.HEALTH_CHECK_INTERVAL_SECONDS", 0.01),
    ):
        result = await session.execute(remote_host="ubuntu@gpu-server.local")
        assert result.status.name == "FAILED"
        assert "3 consecutive health check failures" in result.error
        mock_service.disconnect.assert_called_once()


@pytest.mark.anyio
async def test_connect_session_playbook_password_fallback(tmp_path):
    session = ConnectSession()

    active = ActiveSession(
        remote_host="gpu-server.local",
        local_prefect_port=4201,
        local_ollama_port=11435,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
    )
    mock_service = MagicMock()
    # First call (without password) raises auth error, second call (with password) succeeds
    mock_service.connect.side_effect = [RuntimeError("No public key available"), active]

    with (
        patch(
            "pirlo.playbooks.connect.main.ConnectService.create_default",
            return_value=mock_service,
        ),
        patch.object(session, "_monitor_health_loop", new_callable=AsyncMock),
        patch("sys.stdin.isatty", return_value=True),
        patch.object(
            session.ui,
            "prompt_password",
            new_callable=AsyncMock,
            return_value="mysecretpass",
        ),
    ):
        result = await session.execute(remote_host="ubuntu@gpu-server.local")
        assert result.status.name == "COMPLETED"
        assert result.data["remote_host"] == "gpu-server.local"
        assert mock_service.connect.call_count == 2
        mock_service.connect.assert_called_with(
            remote_host="gpu-server.local",
            ssh_user="ubuntu",
            ssh_port=22,
            ssh_password="mysecretpass",
        )
