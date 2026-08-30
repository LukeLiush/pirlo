import shutil
from pathlib import Path

from pirlo.core.config import get_workspace_path
from pirlo.core.models.link import LlmLink
from pirlo.core.models.serve_manifest import ActiveSession, ServeManifest
from pirlo.core.ports.health_checker import (
    CompositeHealthChecker,
    HealthStatus,
    OllamaHealthChecker,
    PrefectHealthChecker,
    ServiceHealthChecker,
)
from pirlo.core.ports.remote_manifest_prober import RemoteManifestProber
from pirlo.core.ports.tunnel_manager import TunnelConfig, TunnelManager
from pirlo.infrastructure.adapters.ssh.paramiko_manifest_prober import (
    ParamikoManifestProber,
)
from pirlo.infrastructure.adapters.ssh.sshtunnel_manager import SshTunnelManager
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)


class ConnectService:
    """Domain Application Service orchestrating connection via pure dependency injection."""

    def __init__(
        self,
        prober: RemoteManifestProber,
        tunnel_manager: TunnelManager,
        health_checker: ServiceHealthChecker,
        connect_dir: Path | None = None,
    ) -> None:
        self.prober = prober
        self.tunnel_manager = tunnel_manager
        self.health_checker = health_checker
        self.connect_dir = connect_dir or (get_workspace_path() / "connect")

    @classmethod
    def create_default(cls, connect_dir: Path | None = None) -> "ConnectService":
        """Factory method for instantiating production CLI infrastructure adapters."""
        return cls(
            prober=ParamikoManifestProber(),
            tunnel_manager=SshTunnelManager(),
            health_checker=CompositeHealthChecker(
                [
                    PrefectHealthChecker(),
                    OllamaHealthChecker(),
                ]
            ),
            connect_dir=connect_dir,
        )

    def connect(
        self,
        remote_host: str = "localhost",
        ssh_user: str = "ubuntu",
        ssh_port: int = 22,
    ) -> ActiveSession | None:

        from pirlo.infrastructure.adapters.storage.local_manifest_prober import (
            LocalManifestProber,
        )

        target_host = remote_host.strip() if remote_host else "localhost"
        is_local = target_host.lower() in ("localhost", "127.0.0.1", "local")

        self.connect_dir.mkdir(parents=True, exist_ok=True)
        session_file: Path = self.connect_dir / "session.json"
        existing_session: ActiveSession | None = ActiveSession.load_active(session_file)

        # 1. Same-Host Liveness Check
        if existing_session and existing_session.is_alive():
            if existing_session.is_same_host(target_host):
                print(
                    f"[pirlo connect] Already connected to {target_host}. Reusing active session."
                )
                return existing_session
            else:
                print(
                    f"[pirlo connect] Closing existing connection to {existing_session.remote_host}..."
                )
                self.disconnect()

        if is_local:
            print("[pirlo connect] Auto-detecting local pirlo serve instance...")
            manifest: ServeManifest = LocalManifestProber().fetch_manifest("localhost")
            if not manifest.default_prefect_port:
                print(
                    "[pirlo connect] [ERROR] No local pirlo serve instance found. Run 'pirlo serve' first."
                )
                return None

            session = ActiveSession(
                remote_host="localhost",
                local_prefect_port=manifest.default_prefect_port,
                local_ollama_port=manifest.default_ollama_port,
                remote_prefect_port=manifest.default_prefect_port,
                remote_ollama_port=manifest.default_ollama_port,
                tunnel_pid=None,
            )

        else:
            # 2. Probe Remote Manifest via Injected Prober Port
            manifest = self.prober.fetch_manifest(
                target_host, ssh_user=ssh_user, ssh_port=ssh_port
            )

            # 3. Open SSH Tunnels via Injected TunnelManager Port
            config = TunnelConfig(
                remote_host=target_host,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
                remote_prefect_port=manifest.default_prefect_port,
                remote_ollama_port=manifest.default_ollama_port,
            )
            tunnel = self.tunnel_manager.open_tunnel(config)

            session = ActiveSession(
                remote_host=target_host,
                local_prefect_port=tunnel.local_prefect_port,
                local_ollama_port=tunnel.local_ollama_port,
                remote_prefect_port=manifest.default_prefect_port,
                remote_ollama_port=manifest.default_ollama_port,
                tunnel_pid=tunnel.pid,
            )

        # 4. Health Check Verification via Injected ServiceHealthChecker Port
        print(f"[pirlo connect] Verifying service health for {session.remote_host}...")
        status = self.health_checker.check_health(session)
        print(status.message)

        if not status.is_healthy:
            print(f"[pirlo connect] [ERROR] Health check failed on {target_host}.")
            if not is_local:
                self.tunnel_manager.close_tunnel()
            return None

        # 5. Save ActiveSession state & register overlay links
        session.save(session_file)
        self._register_overlay_links(session, manifest.models, manifest.default_model)
        return session

    def _register_overlay_links(
        self, session: ActiveSession, models: list[str], default_model: str
    ) -> None:
        connect_repo = JsonLinkRepository(self.connect_dir / "links.json")
        for model in models:
            if model == default_model:
                link_name = "serve-ollama"
            else:
                sanitized_model = model.replace(":", "-").replace(".", "-")
                link_name = f"serve-ollama-{sanitized_model}"

            link = LlmLink(
                name=link_name,
                provider="ollama",
                model=model,
                api_key="ollama",
                base_url=session.ollama_base_url,
                source="pirlo-connect",
            )
            connect_repo.save(link)

    def disconnect(self) -> None:
        self.tunnel_manager.close_tunnel()
        if self.connect_dir.exists():
            shutil.rmtree(self.connect_dir)
        print("[pirlo connect] Connection closed cleanly.")

    def get_status(self) -> tuple[ActiveSession | None, HealthStatus | None]:
        session_file: Path = self.connect_dir / "session.json"
        session: ActiveSession | None = ActiveSession.load_active(session_file)
        if not session:
            return None, None
        status = self.health_checker.check_health(session)
        return session, status
