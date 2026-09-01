from pathlib import Path
from typing import Any

import psutil

from pirlo.playbooks.connect.ports.tunnel_manager import (
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
        import paramiko

        if not hasattr(paramiko, "DSSKey"):

            class DummyDSSKey(paramiko.PKey):
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    raise paramiko.SSHException("DSSKey is deprecated and unsupported")

            paramiko.DSSKey = DummyDSSKey

        from sshtunnel import SSHTunnelForwarder

        kwargs: dict[str, Any] = {
            "ssh_username": config.ssh_user,
        }

        if config.ssh_password:
            kwargs["ssh_password"] = config.ssh_password
        else:
            # Auto-detect default SSH key files if present in ~/.ssh/
            for key_name in ("id_ed25519", "id_rsa", "id_ecdsa"):
                key_path = Path(f"~/.ssh/{key_name}").expanduser()
                if key_path.exists():
                    kwargs["ssh_pkey"] = str(key_path)
                    break

        try:
            self._prefect_tunnel = SSHTunnelForwarder(
                (config.remote_host, config.ssh_port),
                remote_bind_address=("127.0.0.1", config.remote_prefect_port),
                local_bind_address=("127.0.0.1", 0),
                **kwargs,
            )
            self._prefect_tunnel.start()

            self._ollama_tunnel = SSHTunnelForwarder(
                (config.remote_host, config.ssh_port),
                remote_bind_address=("127.0.0.1", config.remote_ollama_port),
                local_bind_address=("127.0.0.1", 0),
                **kwargs,
            )
            self._ollama_tunnel.start()
        except Exception as e:
            print(
                f"[pirlo connect] [ERROR] Failed to open SSH tunnel to {config.remote_host}: {e}"
            )
            self.close_tunnel()
            raise RuntimeError(f"SSH Tunnel failed to {config.remote_host}: {e}") from e

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
