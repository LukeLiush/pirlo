from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TunnelConfig:
    remote_host: str
    ssh_user: str
    ssh_port: int
    remote_prefect_port: int
    remote_ollama_port: int


@dataclass
class ActiveTunnel:
    local_prefect_port: int
    local_ollama_port: int
    pid: int


class TunnelManager(ABC):
    """Port for opening and managing background SSH tunnels."""

    @abstractmethod
    def open_tunnel(self, config: TunnelConfig) -> ActiveTunnel:
        """Establishes background SSH port forwards."""

    @abstractmethod
    def close_tunnel(self) -> None:
        """Tears down active background SSH port forwards."""
