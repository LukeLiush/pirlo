from typing import Annotated, Any

from pirlo.core.decorators import playbook
from pirlo.core.domain.connect.connect_service import ConnectService
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.pitch import Pitch


@playbook(
    name="connect",
    description="Connects to a remote pirlo serve instance via Paramiko SSH tunnels.",
)
class ConnectSession(Pitch):
    """Connect playbook that establishes SSH tunnels and registers link overlays."""

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
        run_id_val = (
            (await self.prepared_run()).run_id if self._prepared_run else "connect-run"
        )
        service = ConnectService.create_default()

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
            active_session, health_status = service.get_status()
            if not active_session:
                self.ui.commentary("No active pirlo connect session.")
                return RunResult(
                    run_id=run_id_val,
                    status=RunStatus.COMPLETED,
                    data={"active": False},
                )

            detail_msg = (
                f"Remote Host: {active_session.remote_host}\n"
                f"Prefect API: {active_session.prefect_api_url}\n"
                f"Ollama Base: {active_session.ollama_base_url}\n"
                f"Health: {'HEALTHY' if health_status and health_status.is_healthy else 'UNHEALTHY'}\n"
                f"{health_status.message if health_status else ''}"
            )
            self.ui.goal("Active Session Status", detail=detail_msg)
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.COMPLETED,
                data={
                    "active": True,
                    "remote_host": active_session.remote_host,
                },
            )

        # 3. Connect Handler (pirlo connect [remote_host])
        target = remote_host.strip() if remote_host else "localhost"
        is_local = target.lower() in ("localhost", "127.0.0.1", "local")

        subtitle_str = (
            "Auto-detecting local pirlo serve instance"
            if is_local
            else f"Connecting to remote host: {target}"
        )
        self.ui.header("Pirlo Connect Engine", subtitle=subtitle_str)

        ssh_user = "ubuntu"
        host_target = target
        if "@" in target:
            ssh_user, host_target = target.split("@", 1)

        try:
            session = service.connect(
                remote_host=host_target, ssh_user=ssh_user, ssh_port=ssh_port
            )
        except Exception as e:  # noqa: BLE001
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

        self.ui.goal(
            "Connected to remote pirlo serve successfully!",
            detail=(
                f"Remote Host: {session.remote_host}\n"
                f"Local Prefect Tunnel: {session.prefect_api_url}\n"
                f"Local Ollama Tunnel: {session.ollama_base_url}\n\n"
                f"💡 To disconnect at any time, run:\n"
                f"   pirlo connect --down"
            ),
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
