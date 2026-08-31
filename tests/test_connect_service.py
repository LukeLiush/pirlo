from pathlib import Path
from unittest.mock import patch

from pirlo.core.models.serve_manifest import ActiveSession, ServeManifest
from pirlo.core.ports.health_checker import HealthStatus, ServiceHealthChecker
from pirlo.playbooks.connect.domain.connect_service import ConnectService
from pirlo.playbooks.connect.ports.remote_manifest_prober import RemoteManifestProber
from pirlo.playbooks.connect.ports.tunnel_manager import (
    ActiveTunnel,
    TunnelConfig,
    TunnelManager,
)


class MockProber(RemoteManifestProber):
    def fetch_manifest(
        self,
        remote_host: str,
        ssh_user: str = "ubuntu",
        ssh_port: int = 22,
        ssh_password: str | None = None,
    ) -> ServeManifest:
        self.last_ssh_password = ssh_password
        return ServeManifest(
            default_prefect_port=4200,
            default_ollama_port=11434,
            default_model="qwen2.5",
            models=["qwen2.5", "deepseek-r1:8b"],
        )


class MockTunnelManager(TunnelManager):
    def __init__(self):
        self.opened = False
        self.closed = False

    def open_tunnel(self, config: TunnelConfig) -> ActiveTunnel:
        self.opened = True
        return ActiveTunnel(local_prefect_port=4201, local_ollama_port=11435, pid=99999)

    def close_tunnel(self) -> None:
        self.closed = True


class MockHealthyServiceChecker(ServiceHealthChecker):
    @property
    def service_name(self) -> str:
        return "mock_all"

    def check_health(
        self, session: ActiveSession, timeout_seconds: float = 2.0
    ) -> HealthStatus:
        return HealthStatus(
            is_healthy=True, service_name=self.service_name, message="Healthy"
        )


def test_connect_service_successful_connection(tmp_path: Path):
    connect_dir = tmp_path / "connect"
    prober = MockProber()
    tunnel_mgr = MockTunnelManager()
    health_checker = MockHealthyServiceChecker()

    service = ConnectService(
        prober=prober,
        tunnel_manager=tunnel_mgr,
        health_checker=health_checker,
        connect_dir=connect_dir,
    )

    session = service.connect(remote_host="gpu-node.internal", ssh_user="ubuntu")
    assert session is not None
    assert session.remote_host == "gpu-node.internal"
    assert session.local_prefect_port == 4201
    assert session.local_ollama_port == 11435
    assert tunnel_mgr.opened

    # Verify session file written
    assert (connect_dir / "session.json").exists()

    # Verify overlay links written to connect/links.json
    overlay_links_file = connect_dir / "links.json"
    assert overlay_links_file.exists()

    from pirlo.infrastructure.adapters.storage.json_link_repository import (
        JsonLinkRepository,
    )

    repo = JsonLinkRepository(overlay_links_file)
    default_link = repo.get_by_name("serve-ollama")
    assert default_link is not None
    assert default_link.is_default is True

    # Test disconnect
    service.disconnect()
    assert tunnel_mgr.closed
    assert not connect_dir.exists()


def test_connect_service_local_autodiscovery(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir(parents=True, exist_ok=True)

    manifest = ServeManifest(
        default_prefect_port=4200,
        default_ollama_port=11434,
        default_model="qwen2.5",
        models=["qwen2.5"],
    )
    manifest.save(serve_dir / "serve.json")

    connect_dir = tmp_path / "connect"
    prober = MockProber()
    tunnel_mgr = MockTunnelManager()
    health_checker = MockHealthyServiceChecker()

    service = ConnectService(
        prober=prober,
        tunnel_manager=tunnel_mgr,
        health_checker=health_checker,
        connect_dir=connect_dir,
    )

    session = service.connect(remote_host="localhost")
    assert session is not None
    assert session.remote_host == "localhost"
    assert session.local_prefect_port == 4200
    assert session.local_ollama_port == 11434
    assert not tunnel_mgr.opened  # Local connect bypasses SSH tunnel!


def test_connect_service_replaces_previous(tmp_path: Path):
    connect_dir = tmp_path / "connect"
    prober = MockProber()
    tunnel_mgr = MockTunnelManager()
    health_checker = MockHealthyServiceChecker()

    service = ConnectService(
        prober=prober,
        tunnel_manager=tunnel_mgr,
        health_checker=health_checker,
        connect_dir=connect_dir,
    )

    session1 = service.connect(remote_host="gpu-node.internal", ssh_user="ubuntu")
    assert session1 is not None

    with patch.object(ActiveSession, "is_alive", return_value=True):
        session2 = service.connect(remote_host="gpu-node.internal", ssh_user="ubuntu")
        assert session2 is not None
        assert tunnel_mgr.closed


def test_connect_service_with_password(tmp_path: Path):
    connect_dir = tmp_path / "connect"
    prober = MockProber()
    tunnel_mgr = MockTunnelManager()
    health_checker = MockHealthyServiceChecker()

    service = ConnectService(
        prober=prober,
        tunnel_manager=tunnel_mgr,
        health_checker=health_checker,
        connect_dir=connect_dir,
    )

    session = service.connect(
        remote_host="gpu-node.internal",
        ssh_user="ubuntu",
        ssh_password="secretpassword123",
    )
    assert session is not None
    assert prober.last_ssh_password == "secretpassword123"
