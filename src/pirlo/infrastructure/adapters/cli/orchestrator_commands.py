from __future__ import annotations

import argparse
import sys
from typing import Any

from pirlo.core.config import get_workspace_path
from pirlo.core.models.orchestrator import OrchestratorLink
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.orchestrator_repository import OrchestratorRepository
from pirlo.infrastructure.adapters.orchestrator.registry import (
    OrchestratorRegistry,
)
from pirlo.infrastructure.adapters.storage.json_orchestrator_repository import (
    JsonOrchestratorRepository,
)


def get_orchestrator_repo() -> OrchestratorRepository:
    return JsonOrchestratorRepository(get_workspace_path() / "orchestrators.json")


def extract_link_parameters(
    link_cls: type[OrchestratorLink],
) -> list[dict[str, Any]]:
    """Extracts CLI parameter metadata from an OrchestratorLink class."""
    params: list[dict[str, Any]] = []
    for field_name, field_info in link_cls.model_fields.items():
        if field_name in ("name", "engine"):
            continue

        param_meta: Parameter | None = None
        for meta in field_info.metadata:
            if isinstance(meta, Parameter):
                param_meta = meta
                break

        default_val = field_info.default if field_info.default is not Ellipsis else None
        help_text = (
            param_meta.help
            if param_meta and param_meta.help
            else field_info.description
        )

        params.append(
            {
                "name": field_name,
                "type": field_info.annotation,
                "default": default_val,
                "help": help_text,
                "short": param_meta.short if param_meta else None,
            }
        )
    return params


def orchestrator_main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage workflow orchestrator connections.",
        prog="pirlo orchestrator",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. list
    subparsers.add_parser("list", help="List all registered orchestrator links")

    # 2. create (interactive wizard when called without engine, or engine subcommand)
    create_parser = subparsers.add_parser(
        "create",
        help="Create an orchestrator link (run interactively or choose an engine)",
    )
    create_subparsers = create_parser.add_subparsers(dest="engine", metavar="ENGINE")

    for engine_name in OrchestratorRegistry.list_engines():
        plugin = OrchestratorRegistry.get(engine_name)
        link_cls = OrchestratorRegistry.get_orchestrator_link_cls(engine_name)
        engine_doc = (
            (plugin.__doc__ or f"Create a {engine_name} orchestrator link")
            .strip()
            .split("\n")[0]
        )

        engine_parser = create_subparsers.add_parser(
            engine_name,
            help=engine_doc,
            description=plugin.__doc__
            or f"Configure a {engine_name} orchestrator connection.",
        )
        engine_parser.add_argument("name", help="Link Name (e.g. prod, staging)")

        for param in extract_link_parameters(link_cls):
            flag = f"--{param['name'].replace('_', '-')}"
            help_msg = param["help"] or f"{param['name']} setting"
            if param["default"] is not None:
                help_msg = f"{help_msg} (default: {param['default']})"

            param_type: type[Any] = str
            origin_type = param["type"]
            if origin_type is int:
                param_type = int
            elif origin_type is float:
                param_type = float

            kwargs: dict[str, Any] = {
                "type": param_type,
                "default": param["default"],
                "help": help_msg,
            }
            if param["short"]:
                engine_parser.add_argument(param["short"], flag, **kwargs)
            else:
                engine_parser.add_argument(flag, **kwargs)

        engine_parser.add_argument(
            "--verify",
            action="store_true",
            help="Verify connection after creation",
        )

    # 3. show
    show_parser = subparsers.add_parser(
        "show", help="Show details of a specific orchestrator link"
    )
    show_parser.add_argument("name", help="Link Name")

    # 4. verify
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify connectivity and readiness of an orchestrator link",
    )
    verify_parser.add_argument("name", help="Link Name")

    # 5. delete
    delete_parser = subparsers.add_parser(
        "delete", help="Delete a specific orchestrator link"
    )
    delete_parser.add_argument("name", help="Link Name")

    args = parser.parse_args(sys.argv[2:])
    repo = get_orchestrator_repo()

    if args.subcommand == "list":
        run_list(repo)
    elif args.subcommand == "create":
        if getattr(args, "engine", None) is None:
            run_interactive_create(repo)
        else:
            run_engine_create(repo, args)
    elif args.subcommand == "show":
        run_show(repo, args.name)
    elif args.subcommand == "verify":
        run_verify(repo, args.name)
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


def run_interactive_create(repo: OrchestratorRepository) -> None:
    engines = OrchestratorRegistry.list_engines()
    if not engines:
        print("Error: No orchestrator engines are registered.")
        sys.exit(1)

    print("? Select Orchestrator Engine:")
    for idx, eng in enumerate(engines, 1):
        plugin = OrchestratorRegistry.get(eng)
        doc = (plugin.__doc__ or f"{eng.capitalize()} Engine").strip().split("\n")[0]
        print(f"  {idx}. {eng:<12} ({doc})")

    while True:
        try:
            choice = input(f"Select choice (1-{len(engines)}): ").strip()
            selected_engine = engines[int(choice) - 1]
            break
        except (ValueError, IndexError):
            print("Invalid selection. Try again.")

    plugin = OrchestratorRegistry.get(selected_engine)
    link_cls = OrchestratorRegistry.get_orchestrator_link_cls(selected_engine)

    name = ""
    while not name:
        name = input("? Link Name (e.g. prod, staging): ").strip()
        if not name:
            print("Error: Link name cannot be empty.")

    field_values: dict[str, Any] = {"name": name}
    for param in extract_link_parameters(link_cls):
        field_name = param["name"]
        default_val = param["default"] or ""
        default_hint = f" [{default_val}]" if default_val else ""
        prompt_label = param["help"] or field_name.replace("_", " ").title()
        val = input(f"? {prompt_label}{default_hint}: ").strip()
        field_values[field_name] = val if val else default_val

    link = link_cls.model_validate(field_values)

    ans = input("? Verify connection now? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        print(f"Verifying connection to '{link.name}' ({link.engine})...")
        res = plugin.verify(link)
        if res.success:
            print(f"✓ {res.message}")
        else:
            print(f"⚠ Verification warning: {res.message}")

    repo.save(link)
    print(f"✓ Orchestrator link '{name}' ({link.engine}) created successfully.")


def run_engine_create(repo: OrchestratorRepository, args: argparse.Namespace) -> None:
    engine_name = args.engine
    plugin = OrchestratorRegistry.get(engine_name)
    link_cls = OrchestratorRegistry.get_orchestrator_link_cls(engine_name)

    field_values: dict[str, Any] = {"name": args.name}
    for param in extract_link_parameters(link_cls):
        field_name = param["name"]
        if hasattr(args, field_name):
            val = getattr(args, field_name)
            if val is not None:
                field_values[field_name] = val

    link = link_cls.model_validate(field_values)

    if getattr(args, "verify", False):
        print(f"Verifying connection to '{link.name}' ({link.engine})...")
        res = plugin.verify(link)
        if res.success:
            print(f"✓ {res.message}")
        else:
            print(f"⚠ Verification warning: {res.message}")

    repo.save(link)
    print(f"✓ Orchestrator link '{link.name}' ({link.engine}) created successfully.")


def run_show(repo: OrchestratorRepository, name: str) -> None:
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)

    print(f"Orchestrator Link: {link.name}")
    print(f"  Engine:     {link.engine}")
    for k, v in link.model_dump(mode="json", exclude_none=True).items():
        if k not in ("name", "engine"):
            print(f"  {k}: {v}")


def run_verify(repo: OrchestratorRepository, name: str) -> bool:
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)

    print(f"Verifying orchestrator link '{name}' ({link.engine})...")
    plugin = OrchestratorRegistry.get(link.engine)
    result = plugin.verify(link)
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


def run_delete(repo: OrchestratorRepository, name: str) -> None:
    if repo.delete(name):
        print(f"✓ Orchestrator link '{name}' deleted successfully.")
    else:
        print(f"Error: Orchestrator link '{name}' not found.")
        sys.exit(1)
