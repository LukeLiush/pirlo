import asyncio
import getpass
import sys
from typing import Annotated, Any

from tenacity import (
    RetryError,
)

from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.models.serve_manifest import ActiveSession
from pirlo.core.ports.health_checker import HealthStatus
from pirlo.core.ports.playbook import Playbook
from pirlo.playbooks.connect.domain.connect_service import ConnectService

HEALTH_CHECK_INTERVAL_SECONDS: float = 15.0
MAX_CONSECUTIVE_FAILURES: int = 3


class UnhealthyServiceError(Exception):
    """Raised inside health monitor loop to trigger tenacity retries."""

    def __init__(self, status: HealthStatus) -> None:
        self.status = status
        super().__init__(status.message)


@playbook(
    name="connect",
    description="Connects to a remote pirlo serve instance via Paramiko SSH tunnels.",
)
class ConnectSession(Playbook):
    """Connect playbook that establishes SSH tunnels and registers link overlays."""

    async def _monitor_health_loop(
        self, session: ActiveSession, service: ConnectService
    ) -> None:
        """Runs continuously in a while True loop, stopping only on N consecutive failures."""
        consecutive_failures: int = 0
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
            status: HealthStatus = service.health_checker.check_health(session)

            if status.is_healthy:
                if consecutive_failures > 0:
                    self.ui.commentary(
                        f"[PASS] Connection health recovered on {session.remote_host}!\n"
                    )
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                self.ui.commentary(
                    f"[WARN] Health check failed ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}) "
                    f"on {session.remote_host}: {status.message}\n"
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise UnhealthyServiceError(status)

    async def play(
        self,
        remote_host: Annotated[
            str,
            Parameter(help="Remote SSH host string (e.g. ubuntu@gpu-server.local)"),
        ] = "",
        down: Annotated[
            bool,
            Parameter(help="Disconnect active remote connect session", short="-d"),
        ] = False,
        disconnect: Annotated[bool, Parameter(help="Alias for --down")] = False,
        status: Annotated[
            bool,
            Parameter(help="Show status of active remote session", short="-s"),
        ] = False,
        ssh_port: Annotated[int, Parameter(help="SSH port on remote host")] = 22,
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any]:
        run_id_val: str = (
            (await self.prepared_run()).run_id if self._prepared_run else "connect-run"
        )
        service: ConnectService = ConnectService.create_default()

        # 1. Disconnect Handler (pirlo connect --down / --disconnect)
        if down or disconnect:
            self.ui.header(
                "Pirlo Connect Engine", subtitle="Disconnecting Remote Session"
            )
            service.disconnect()
            self.ui.goal("Disconnected active remote session cleanly.")
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.COMPLETED,
                data={"status": "disconnected"},
            )

        # 2. Status Handler (pirlo connect --status)
        if status:
            self.ui.header("Pirlo Connect Engine", subtitle="Active Session Status")
            active_session: ActiveSession | None
            health_status: HealthStatus | None
            active_session, health_status = service.get_status()

            if not active_session:
                self.ui.commentary("No active pirlo connect session.")
                return RunResult(
                    run_id=run_id_val,
                    status=RunStatus.COMPLETED,
                    data={"active": False},
                )

            dashboard_url = active_session.prefect_api_url.rstrip("/").replace(
                "/api", ""
            )
            models_str = (
                ", ".join(active_session.models) if active_session.models else "N/A"
            )
            detail_msg: str = (
                f"Remote Host: {active_session.remote_host}\n"
                f"Prefect Dashboard: {dashboard_url}\n"
                f"Ollama Endpoint: {active_session.ollama_base_url}\n"
                f"Available Models: {models_str}\n"
                f"CLI Process PID: {active_session.cli_pid or 'N/A'}\n"
                f"SSH Keep-Alive: {active_session.ssh_keepalive_interval:.0f}s\n"
                f"Health Monitor: Every {HEALTH_CHECK_INTERVAL_SECONDS:.0f}s (max {MAX_CONSECUTIVE_FAILURES} failures)\n"
                f"Health: {'HEALTHY' if health_status and health_status.is_healthy else 'UNHEALTHY'}\n"
                f"{health_status.message if health_status else ''}\n\n"
                f"💡 List models: curl {active_session.ollama_base_url}/api/tags"
            )
            self.ui.goal("Active Session Status", detail=detail_msg)
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.COMPLETED,
                data={
                    "active": True,
                    "remote_host": active_session.remote_host,
                    "cli_pid": active_session.cli_pid,
                },
            )

        # 3. Connect Handler (pirlo connect [remote_host])
        target: str = remote_host.strip() if remote_host else "localhost"
        is_local: bool = target.lower() in ("localhost", "127.0.0.1", "local")

        subtitle_str: str = (
            "Auto-detecting local pirlo serve instance"
            if is_local
            else f"Connecting to remote host: {target}"
        )
        self.ui.header("Pirlo Connect Engine", subtitle=subtitle_str)

        ssh_user: str = getpass.getuser()
        host_target: str = target
        if "@" in target:
            ssh_user, host_target = target.split("@", 1)
        elif not is_local:
            self.ui.commentary(
                f"[INFO] No SSH username specified for '{target}'. Defaulting to current OS user '{ssh_user}'. "
                "(Use 'user@host' to override).\n"
            )

        session: ActiveSession | None = None
        try:
            session = service.connect(
                remote_host=host_target,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
            )

        except Exception as initial_err:  # noqa: BLE001
            e: Exception = initial_err
            # Fallback: If initial SSH key auth fails and in interactive TTY, prompt for password
            if sys.stdin.isatty():
                try:
                    ssh_pass = await self.ui.prompt_password(
                        f"Enter SSH password for {ssh_user}@{host_target}"
                    )
                    if ssh_pass:
                        session = service.connect(
                            remote_host=host_target,
                            ssh_user=ssh_user,
                            ssh_port=ssh_port,
                            ssh_password=ssh_pass,
                        )
                        if session:
                            self.ui.commentary(
                                "🔑 Connected using password. Installed local SSH key to remote host for future passwordless sessions.\n"
                            )
                except Exception as retry_err:  # noqa: BLE001
                    e = retry_err

            if not session:
                self.ui.commentary(
                    f"[ERROR] Failed to establish connection to {remote_host}.\nDetails: {e}\n"
                )
                self.ui.commentary(
                    "💡 Troubleshooting Steps:\n"
                    f"   1. Ensure SSH server (sshd) is running on {host_target} (port {ssh_port}):\n"
                    "      • macOS: Enable System Settings > Sharing > Remote Login\n"
                    "      • Linux: Ensure 'sudo systemctl status ssh' is active\n"
                    "   2. Verify your SSH credentials and identity key (~/.ssh/id_rsa or id_ed25519):\n"
                    f"      • Test manually in terminal: ssh {remote_host}\n"
                )
                return RunResult(
                    run_id=run_id_val,
                    status=RunStatus.FAILED,
                    error=f"Connection to {remote_host} failed: {e}",
                )

        if not session:
            self.ui.commentary(
                f"[ERROR] Failed to establish connection to {remote_host}"
            )
            self.ui.commentary(
                "💡 Troubleshooting Steps:\n"
                "   1. Ensure 'pirlo serve' is active on the remote host.\n"
                f'   2. Verify remote manifest file by running: ssh {remote_host} "cat ~/.pirlo-pitch/serve/serve.json"\n'
            )
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error=f"Connection to {remote_host} failed",
            )

        dashboard_url = session.prefect_api_url.rstrip("/").replace("/api", "")
        models_str = ", ".join(session.models) if session.models else "N/A"
        self.ui.goal(
            "Connected to pirlo serve successfully!",
            detail=(
                f"Remote Host: {session.remote_host}\n"
                f"Prefect Dashboard: {dashboard_url}\n"
                f"Ollama Endpoint: {session.ollama_base_url}\n"
                f"Available Models: {models_str}\n"
                f"SSH Keep-Alive: {session.ssh_keepalive_interval:.0f}s\n"
                f"Health Monitor: Every {HEALTH_CHECK_INTERVAL_SECONDS:.0f}s (max {MAX_CONSECUTIVE_FAILURES} failures)\n\n"
                f"💡 List models via Ollama API: curl {session.ollama_base_url}/api/tags\n"
                f"💡 Press Ctrl+C at any time to disconnect cleanly."
            ),
        )

        try:
            await self._monitor_health_loop(session, service)
        except (RetryError, UnhealthyServiceError):
            total_seconds: float = (
                MAX_CONSECUTIVE_FAILURES * HEALTH_CHECK_INTERVAL_SECONDS
            )
            self.ui.commentary(
                f"\n[ERROR] Connection failed {MAX_CONSECUTIVE_FAILURES} consecutive times "
                f"({total_seconds:.0f}s). Closing session and exiting."
            )
            service.disconnect()
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error=f"Connection failed after {MAX_CONSECUTIVE_FAILURES} consecutive health check failures.",
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.ui.commentary(
                "\n[pirlo connect] Interrupt received. Closing connection and cleaning session..."
            )
            service.disconnect()
            self.ui.goal("Disconnected cleanly.")
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.COMPLETED,
                data={"status": "disconnected"},
            )

        return RunResult(
            run_id=run_id_val,
            status=RunStatus.COMPLETED,
            data={
                "remote_host": session.remote_host,
                "prefect_api_url": session.prefect_api_url,
                "ollama_base_url": session.ollama_base_url,
            },
        )


if __name__ == "__main__":
    ConnectSession.cli()
