from typing import Any

import psutil

from pirlo.core.ports.tunnel_manager import (
    ActiveTunnel,
    TunnelConfig,
    TunnelManager,
)


class SshTunnelManager(TunnelManager):
    """Paramiko SSHTunnelForwarder implementation of TunnelManager."""

    def __init__(self) -> None:
        self._prefect_tunnel: Any | None = None
        self._ollama_tunnel: Any | None = None

    def open_tunnel(self, config: TunnelConfig) -> ActiveTunnel:
        from sshtunnel import SSHTunnelForwarder

        self._prefect_tunnel = SSHTunnelForwarder(
            (config.remote_host, config.ssh_port),
            ssh_username=config.ssh_user,
            remote_bind_address=("127.0.0.1", config.remote_prefect_port),
            local_bind_address=("127.0.0.1", 0),
        )
        self._prefect_tunnel.start()

        self._ollama_tunnel = SSHTunnelForwarder(
            (config.remote_host, config.ssh_port),
            ssh_username=config.ssh_user,
            remote_bind_address=("127.0.0.1", config.remote_ollama_port),
            local_bind_address=("127.0.0.1", 0),
        )
        self._ollama_tunnel.start()

        return ActiveTunnel(
            local_prefect_port=self._prefect_tunnel.local_bind_port,
            local_ollama_port=self._ollama_tunnel.local_bind_port,
            pid=psutil.Process().pid,
        )

    def close_tunnel(self) -> None:
        if self._prefect_tunnel:
            try:
                self._prefect_tunnel.stop()
            except Exception:  # noqa: BLE001, S110
                pass
            self._prefect_tunnel = None

        if self._ollama_tunnel:
            try:
                self._ollama_tunnel.stop()
            except Exception:  # noqa: BLE001, S110
                pass
            self._ollama_tunnel = None
