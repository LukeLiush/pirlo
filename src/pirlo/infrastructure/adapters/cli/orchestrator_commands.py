from __future__ import annotations

import argparse
import sys

from pirlo.core.config import get_workspace_path
from pirlo.core.ports.orchestrator_repository import OrchestratorRepository
from pirlo.infrastructure.adapters.orchestrator.registry import (
    OrchestratorRegistry,
)
from pirlo.infrastructure.adapters.storage.json_orchestrator_repository import (
    JsonOrchestratorRepository,
)


def get_orchestrator_repo() -> OrchestratorRepository:
    return JsonOrchestratorRepository(get_workspace_path() / "orchestrators.json")


def orchestrator_main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage workflow orchestrator connections.",
        prog="pirlo orchestrator",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. list
    subparsers.add_parser("list", help="List all registered orchestrator links")

    # 2. create
    create_parser = subparsers.add_parser(
        "create", help="Create or update an orchestrator link"
    )
    create_parser.add_argument("name", nargs="?", help="Link Name (e.g. prod, staging)")
    create_parser.add_argument(
        "--engine",
        help=f"Orchestrator engine ({', '.join(OrchestratorRegistry.list_engines()) or 'prefect'})",
    )
    create_parser.add_argument(
        "--server", help="Server API URL (defaults to ephemeral mode)"
    )
    create_parser.add_argument(
        "--work-pool", help="Target work pool / queue (defaults to pirlo-pool)"
    )
    create_parser.add_argument(
        "--verify", action="store_true", help="Verify connection after creation"
    )

    # 3. show
    show_parser = subparsers.add_parser(
        "show", help="Show details of a specific orchestrator link"
    )
    show_parser.add_argument("name", help="Link Name")

    # 4. verify
    verify_parser = subparsers.add_parser(
        "verify", help="Verify connectivity and readiness of an orchestrator link"
    )
    verify_parser.add_argument("name", help="Link Name")

    # 5. engines
    engines_parser = subparsers.add_parser(
        "engines", help="List registered orchestrator engines or view their schema"
    )
    engines_parser.add_argument(
        "engine", nargs="?", help="Engine name (e.g. prefect) to inspect parameters"
    )

    # 6. delete
    delete_parser = subparsers.add_parser(
        "delete", help="Delete a specific orchestrator link"
    )
    delete_parser.add_argument("name", help="Link Name")

    args = parser.parse_args(sys.argv[2:])
    repo = get_orchestrator_repo()

    if args.subcommand == "list":
        run_list(repo)
    elif args.subcommand == "create":
        run_create(repo, args)
    elif args.subcommand == "show":
        run_show(repo, args.name)
    elif args.subcommand == "verify":
        run_verify(repo, args.name)
    elif args.subcommand == "engines":
        run_engines(args.engine)
    elif args.subcommand == "delete":
        run_delete(repo, args.name)


def run_list(repo: OrchestratorRepository) -> None:
    links = repo.list_all()
    if not links:
        print(
            "No orchestrator links registered. Run 'pirlo orchestrator create' to add one.\n"
            "Note: Omitting --orchestrator always defaults to local ephemeral Prefect."
        )
        return

    print("Registered Orchestrator Links:\n")
    print(f"{'Name':<18} {'Engine':<12} {'Server URL':<35} {'Details'}")
    print("─" * 80)
    for link in links:
        server_str = getattr(link, "server_url", "ephemeral") or "ephemeral"
        details_list: list[str] = []
        if hasattr(link, "work_pool") and link.work_pool:
            details_list.append(f"work_pool={link.work_pool}")
        details_str = ", ".join(details_list) if details_list else "-"
        print(f"{link.name:<18} {link.engine:<12} {server_str:<35} {details_str}")


def run_create(repo: OrchestratorRepository, args: argparse.Namespace) -> None:
    name = getattr(args, "name", None)
    engine = getattr(args, "engine", None)
    interactive = not (name and engine)

    if interactive:
        if not name:
            name = input("? Link Name (e.g. prod, staging): ").strip()
            if not name:
                print("Error: Link Name is required.")
                sys.exit(1)

        if not engine:
            available_engines = OrchestratorRegistry.list_engines()
            if not available_engines:
                available_engines = ["prefect"]
            print("? Select Orchestrator Engine:")
            for idx, eng in enumerate(available_engines, 1):
                print(f"  {idx}. {eng}")
            while True:
                try:
                    choice = input(
                        f"Select choice (1-{len(available_engines)}): "
                    ).strip()
                    engine = available_engines[int(choice) - 1]
                    break
                except (ValueError, IndexError):
                    print("Invalid selection. Try again.")

    if not name or not engine:
        print("Error: Name and engine are required.")
        sys.exit(1)

    plugin = OrchestratorRegistry.get(str(engine))
    link = plugin.prompt_create_link(str(name), args, interactive)

    verify_flag = getattr(args, "verify", False)
    if interactive and not verify_flag:
        ans = input("? Verify connection now? [Y/n]: ").strip().lower()
        if ans in ("", "y", "yes"):
            verify_flag = True

    if verify_flag:
        print(f"Verifying connection to '{link.name}' ({link.engine})...")
        res = plugin.verify_connection(link)
        if res.success:
            print(f"✓ {res.message}")
        else:
            print(f"⚠ Verification warning: {res.message}")

    repo.save(link)
    print(f"✓ Orchestrator link '{name}' ({link.engine}) created successfully.")


def run_show(repo: OrchestratorRepository, name: str) -> None:
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)

    print(f"Orchestrator Link: {link.name}")
    print(f"  Engine:     {link.engine}")
    for k, v in link.to_dict().items():
        if k != "engine":
            print(f"  {k}: {v}")


def run_verify(repo: OrchestratorRepository, name: str) -> bool:
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)

    print(f"Verifying orchestrator link '{name}' ({link.engine})...")
    plugin = OrchestratorRegistry.get(link.engine)
    result = plugin.verify_connection(link)
    if result.success:
        print(f"✓ {result.message}")
        if result.details:
            details_str = ", ".join(f"{k}={v}" for k, v in result.details.items())
            print(f"  Details: {details_str}")
        return True
    else:
        print(f"✗ Verification failed: {result.message}")
        if result.details:
            details_str = ", ".join(f"{k}={v}" for k, v in result.details.items())
            print(f"  Details: {details_str}")
        return False


def run_engines(engine_name: str | None) -> None:
    if not engine_name:
        engines = OrchestratorRegistry.list_engines()
        if not engines:
            print("No orchestrator engines registered.")
            return

        print("Registered Orchestrator Engines:\n")
        for eng in engines:
            plugin = OrchestratorRegistry.get(eng)
            doc = (
                (plugin.__doc__ or f"{eng.capitalize()} Orchestrator Plugin")
                .strip()
                .split("\n")[0]
            )
            print(f"  • {eng:<14} {doc}")
        print("\nRun 'pirlo orchestrator engines <engine>' to inspect parameters.")
        return

    if not OrchestratorRegistry.is_registered(engine_name):
        print(f"Error: Orchestrator engine '{engine_name}' not found.")
        sys.exit(1)

    plugin = OrchestratorRegistry.get(engine_name)
    link_cls = plugin.link_cls
    print(f"\nEngine: {engine_name}")
    doc = (plugin.__doc__ or "").strip()
    if doc:
        print(f"Description: {doc}\n")

    print(f"{'Parameter':<18} {'Type':<10} {'Default':<24} {'Description'}")
    print("─" * 78)
    for field_name, field_info in link_cls.model_fields.items():
        if field_name in ("name", "engine"):
            continue
        flag = f"--{field_name.replace('_', '-')}"
        type_annot = field_info.annotation
        type_name = getattr(type_annot, "__name__", str(type_annot))
        default_val = "None" if field_info.default is None else str(field_info.default)
        desc = field_info.description or "-"
        print(f"{flag:<18} {type_name:<10} {default_val:<24} {desc}")
    print("─" * 78)


def run_delete(repo: OrchestratorRepository, name: str) -> None:
    if repo.delete(name):
        print(f"✓ Orchestrator link '{name}' deleted successfully.")
    else:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)
