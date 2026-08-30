import argparse
import sys

from pirlo.core.config import get_workspace_path
from pirlo.core.domain.connect.connect_service import ConnectService
from pirlo.core.models.serve_manifest import ActiveSession
from pirlo.infrastructure.adapters.storage.composite_link_repository import (
    CompositeLinkRepository,
)


def connect_main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage pirlo connect remote session and SSH tunnels.",
        prog="pirlo connect",
    )
    parser.add_argument(
        "remote_host",
        nargs="?",
        help="Target remote host (e.g. user@remote-gpu-server or 192.168.1.100)",
    )
    parser.add_argument(
        "--user",
        "-u",
        default="ubuntu",
        help="SSH username (default: ubuntu)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=22,
        help="SSH port (default: 22)",
    )
    parser.add_argument(
        "--disconnect",
        action="store_true",
        help="Disconnect active remote session and close tunnels",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display active remote connection health status",
    )

    args = parser.parse_args(sys.argv[2:])
    service = ConnectService.create_default()

    if args.disconnect:
        service.disconnect()
        return

    if args.status:
        run_status()
        return

    if not args.remote_host:
        parser.print_help()
        sys.exit(1)

    ssh_user = args.user
    remote_host = args.remote_host
    if "@" in remote_host:
        ssh_user, remote_host = remote_host.split("@", 1)

    session = service.connect(
        remote_host=remote_host, ssh_user=ssh_user, ssh_port=args.port
    )
    if session is None:
        sys.exit(1)


def disconnect_main() -> None:
    service = ConnectService.create_default()
    service.disconnect()


def status_main() -> None:
    run_status()


def run_status() -> None:
    connect_dir = get_workspace_path() / "connect"
    session_file = connect_dir / "session.json"

    session = ActiveSession.load_active(session_file)
    if not session:
        print("No active pirlo connect session.")
        print(
            "Run 'pirlo connect <user@remote-host>' to establish a remote connection."
        )
        return

    print("Active pirlo connect Session:\n")
    print(f"  Remote Host        : {session.remote_host}")
    print(f"  Tunnel Process PID : {session.tunnel_pid}")
    print(f"  Local Prefect API  : {session.prefect_api_url}")
    print(f"  Local Ollama Base  : {session.ollama_base_url}")
    print(
        f"  Tunnel Status      : {'[OK] Healthy' if session.is_alive() else '[FAIL] Dead'}"
    )

    print("\nRegistered Session Overlay Links:\n")
    repo = CompositeLinkRepository()
    links = repo.list_all()
    connect_links = [l for l in links if l.source == "pirlo-connect"]

    if not connect_links:
        print("  No active overlay links registered.")
    else:
        print(f"  {'Name':<24} {'Model':<20} {'Base URL'}")
        print("  " + "─" * 70)
        for link in connect_links:
            print(f"  {link.name:<24} {link.model:<20} {link.base_url}")
