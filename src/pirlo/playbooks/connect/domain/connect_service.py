import os
import shutil
from pathlib import Path

import psutil

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
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)
from pirlo.playbooks.connect.adapters.paramiko_manifest_prober import (
    ParamikoManifestProber,
)
from pirlo.playbooks.connect.adapters.sshtunnel_manager import SshTunnelManager
from pirlo.playbooks.connect.ports.remote_manifest_prober import RemoteManifestProber
from pirlo.playbooks.connect.ports.tunnel_manager import TunnelConfig, TunnelManager


def _fetch_live_models_over_tunnel(ollama_base_url: str) -> list[str]:
    """Queries live Ollama models over established tunnel (http://127.0.0.1:<local_ollama_port>/api/tags)."""
    import json
    import urllib.request

    url = f"{ollama_base_url}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pirlo"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models_info = data.get("models", [])
                return [m.get("name", "") for m in models_info if m.get("name")]
    except Exception:  # noqa: BLE001, S110
        pass
    return []


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

    def _terminate_process(self, pid: int | None) -> None:
        """Gracefully terminates a previous pirlo connect process PID."""
        if not pid or pid == os.getpid():
            return
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=3.0)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            try:
                psutil.Process(pid).kill()
            except Exception:  # noqa: BLE001, S110
                pass

    def connect(
        self,
        remote_host: str = "localhost",
        ssh_user: str = "ubuntu",
        ssh_port: int = 22,
        ssh_password: str | None = None,
    ) -> ActiveSession | None:
        from pirlo.playbooks.connect.adapters.local_manifest_prober import (
            LocalManifestProber,
        )

        target_host = remote_host.strip() if remote_host else "localhost"
        is_local = target_host.lower() in ("localhost", "127.0.0.1", "local")

        self.connect_dir.mkdir(parents=True, exist_ok=True)
        session_file: Path = self.connect_dir / "session.json"
        existing_session: ActiveSession | None = ActiveSession.load_active(session_file)

        # 1. Terminate & replace any existing connection process
        if existing_session and existing_session.is_alive():
            print(
                f"[pirlo connect] Terminating previous connection process "
                f"(PID {existing_session.cli_pid or 'active'})..."
            )
            self._terminate_process(existing_session.cli_pid)
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
                cli_pid=os.getpid(),
            )
        else:
            # 2. Probe Remote Manifest via Injected Prober Port
            manifest = self.prober.fetch_manifest(
                target_host,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
                ssh_password=ssh_password,
            )

            # 3. Open SSH Tunnels via Injected TunnelManager Port
            config = TunnelConfig(
                remote_host=target_host,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
                remote_prefect_port=manifest.default_prefect_port,
                remote_ollama_port=manifest.default_ollama_port,
                ssh_password=ssh_password,
            )
            tunnel = self.tunnel_manager.open_tunnel(config)

            session = ActiveSession(
                remote_host=target_host,
                local_prefect_port=tunnel.local_prefect_port,
                local_ollama_port=tunnel.local_ollama_port,
                remote_prefect_port=manifest.default_prefect_port,
                remote_ollama_port=manifest.default_ollama_port,
                cli_pid=os.getpid(),
                ssh_keepalive_interval=tunnel.ssh_keepalive_interval,
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
        session.models = self._register_overlay_links(
            session, manifest.models, manifest.default_model
        )
        session.save(session_file)
        return session

    def _register_overlay_links(
        self, session: ActiveSession, models: list[str], default_model: str
    ) -> list[str]:
        connect_repo = JsonLinkRepository(self.connect_dir / "links.json")

        live_models = _fetch_live_models_over_tunnel(session.ollama_base_url)
        models_to_link = live_models if live_models else models

        if not live_models:
            print(
                "[pirlo connect] [WARNING] No live models found in Ollama daemon via tunnel. Using manifest fallback."
            )

        selected_default = (
            default_model if default_model in models_to_link else models_to_link[0]
        )

        for model in models_to_link:
            if model == selected_default:
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
                is_default=(model == selected_default),
            )
            connect_repo.save(link)

        return models_to_link

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
