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

        # 3. Connect Handler (pirlo connect <remote_host>)
        if not remote_host:
            self.ui.commentary("[ERROR] Missing required argument: remote_host\n")
            self.ui.commentary(
                "💡 Usage Examples:\n"
                "   • Connect to remote serve:  pirlo connect ubuntu@gpu-server.local\n"
                "   • Disconnect active session: pirlo connect --down\n"
                "   • Show session status:       pirlo connect --status\n"
            )
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error="Missing required remote_host argument",
            )

        self.ui.header(
            "Pirlo Connect Engine",
            subtitle=f"Connecting to remote host: {remote_host}",
        )

        ssh_user = "ubuntu"
        host_target = remote_host
        if "@" in remote_host:
            ssh_user, host_target = remote_host.split("@", 1)

        session = service.connect(
            remote_host=host_target, ssh_user=ssh_user, ssh_port=ssh_port
        )

        if not session:
            self.ui.commentary(
                f"[ERROR] Failed to establish connection to {remote_host}"
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
