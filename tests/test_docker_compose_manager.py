from pathlib import Path
from unittest.mock import MagicMock

from pirlo.infrastructure.adapters.docker.docker_compose_manager import (
    DockerComposeManager,
)


def test_docker_compose_manager_ready_check(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3.8'\nservices: {}\n")

    mock_docker = MagicMock()
    mock_docker.system.info.return_value = {"Containers": 0}
    manager = DockerComposeManager(compose_file=compose_file, client=mock_docker)

    ready, msg = manager.is_docker_ready()
    assert ready
    assert "healthy" in msg


def test_docker_compose_manager_up_success(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3.8'\nservices: {}\n")

    mock_docker = MagicMock()
    mock_docker.system.info.return_value = {"Containers": 0}
    manager = DockerComposeManager(compose_file=compose_file, client=mock_docker)

    success, _msg = manager.up(env_vars={"PREFECT_PORT": "4200"})

    assert success
    mock_docker.compose.up.assert_called_once_with(detach=True)
