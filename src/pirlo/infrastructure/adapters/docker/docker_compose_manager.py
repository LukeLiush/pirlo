from pathlib import Path
from typing import Any


class DockerComposeManager:
    """Pure-Python Docker Compose Manager using python-on-whales."""

    def __init__(self, compose_file: Path, client: Any | None = None) -> None:
        self.compose_file = compose_file
        self._docker = client

    @property
    def docker(self) -> Any:
        if self._docker is None:
            from python_on_whales import DockerClient

            self._docker = DockerClient(compose_files=[self.compose_file])
        return self._docker

    def is_docker_ready(self) -> tuple[bool, str]:
        """Verifies if the Docker daemon is active and responding."""
        try:
            info = self.docker.system.info()
            if info:
                return True, "Docker daemon is healthy."
            return False, "Docker daemon returned empty system info."
        except Exception as e:  # noqa: BLE001
            return False, f"Could not connect to Docker daemon: {e}"

    def up(self, env_vars: dict[str, str]) -> tuple[bool, str]:
        """Brings up the docker-compose.yml stack using native python-on-whales API."""
        ready, msg = self.is_docker_ready()
        if not ready:
            return False, msg

        try:
            import os

            old_env = os.environ.copy()
            os.environ.update(env_vars)
            try:
                self.docker.compose.up(detach=True)
            finally:
                os.environ.clear()
                os.environ.update(old_env)
            return True, "Stack started successfully."
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def down(self) -> tuple[bool, str]:
        """Tears down the docker-compose.yml stack."""
        try:
            self.docker.compose.down()
            return True, "Stack stopped successfully."
        except Exception as e:  # noqa: BLE001
            return False, str(e)
