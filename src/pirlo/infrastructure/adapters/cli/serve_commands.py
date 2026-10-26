from __future__ import annotations

import argparse
import getpass
import socket
import sys

import httpx

from pirlo.core.config import DEFAULT_PREFECT_PORT, DEFAULT_WORK_POOL
from pirlo.core.ports.local_server import (
    LocalServer,
    LocalServerError,
    LocalServerStatus,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_local_server import (
    PrefectLocalServer,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_work_pool import (
    ensure_work_pool,
)


def _ui_url(status: LocalServerStatus) -> str:
    return status.api_url.removesuffix("/api")


def _print_running(status: LocalServerStatus) -> None:
    print(f"Prefect UI:  {_ui_url(status)}")
    print(f"PID:         {status.pid} (since {status.started_at})")
    print(f"Log:         {status.log_path}")


def serve_main(argv: list[str] | None = None, server: LocalServer | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pirlo serve",
        description=(
            "Start a Prefect server on 127.0.0.1 that pirlo runs report to. "
            "It keeps running until 'pirlo serve --stop'."
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "-s", "--status", action="store_true", help="Show whether the server is running"
    )
    action.add_argument(
        "--stop", action="store_true", help="Stop the server pirlo serve started"
    )
    args = parser.parse_args(sys.argv[2:] if argv is None else argv)

    local: LocalServer = server or PrefectLocalServer()

    if args.stop:
        if local.stop():
            print("Stopped the Prefect server.")
        else:
            print("No Prefect server started by pirlo serve is running.")
        return 0

    if args.status:
        running = local.status()
        if running is None:
            print("No Prefect server started by pirlo serve is running.")
            return 1
        _print_running(running)
        return 0

    already = local.status()
    if already is None:
        print("Starting a Prefect server on 127.0.0.1...")
    try:
        status = already or local.start(DEFAULT_PREFECT_PORT)
    except LocalServerError as exc:
        print(f"Couldn't start the Prefect server: {exc}", file=sys.stderr)
        return 1

    print("Prefect server is running." if already else "Prefect server started.")
    _print_running(status)
    try:
        created = ensure_work_pool(status.api_url)
        state = "created" if created else "ready"
        print(f"Work pool:   {DEFAULT_WORK_POOL} ({state}; routines need a worker)")
    except httpx.HTTPError as exc:
        print(
            f"Warning: couldn't check work pool {DEFAULT_WORK_POOL}: {exc}",
            file=sys.stderr,
        )

    print()
    print("Runs now report here: pirlo <play>")
    print("From another machine, tunnel over SSH:")
    print(
        f"  ssh -L {status.port}:127.0.0.1:{status.port} "
        f"{getpass.getuser()}@{socket.gethostname()}"
    )
    print("Stop it with: pirlo serve --stop")
    return 0
