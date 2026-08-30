from pathlib import Path

from pirlo.core.config import get_workspace_path
from pirlo.core.models.serve_manifest import ServeManifest
from pirlo.core.ports.remote_manifest_prober import RemoteManifestProber


class LocalManifestProber(RemoteManifestProber):
    """Local filesystem implementation of RemoteManifestProber for local serve instances."""

    def __init__(self, serve_dir: Path | None = None) -> None:
        self.serve_dir = serve_dir or (get_workspace_path() / "serve")

    def fetch_manifest(
        self, remote_host: str, ssh_user: str = "ubuntu", ssh_port: int = 22
    ) -> ServeManifest:
        manifest_path = self.serve_dir / "serve.json"
        if manifest_path.exists():
            return ServeManifest.load(manifest_path)
        return ServeManifest()
