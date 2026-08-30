from abc import ABC, abstractmethod

from pirlo.core.models.serve_manifest import ServeManifest


class RemoteManifestProber(ABC):
    """Port for probing remote server manifests over SSH or HTTP."""

    @abstractmethod
    def fetch_manifest(
        self,
        remote_host: str,
        ssh_user: str = "ubuntu",
        ssh_port: int = 22,
        ssh_password: str | None = None,
    ) -> ServeManifest:
        """Fetch ServeManifest from target host."""
