from unittest.mock import MagicMock, patch

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

    with patch(
        "pirlo.playbooks.connect.main.ConnectService.create_default",
        return_value=mock_service,
    ):
        result = await session.play(remote_host="ubuntu@gpu-server.local")
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
        result = await session.play(down=True)
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
        result = await session.play(status=True)
        assert result.status.name == "COMPLETED"
        assert result.data["active"]
        assert result.data["remote_host"] == "gpu-server.local"
