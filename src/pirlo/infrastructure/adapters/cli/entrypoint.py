import importlib
import sys
import tomllib
from pathlib import Path

from pirlo.infrastructure.services.playbook_scanner import (
    PlaybookScanner,
    PlaybookSpec,
)


def load_pyproject_playbooks() -> dict[str, str]:
    """Loads playbooks registered in pyproject.toml under [tool.pirlo.playbooks]."""
    playbooks: dict[str, str] = {}
    pyproject_path: Path = Path.cwd() / "pyproject.toml"
    if not pyproject_path.exists():
        current: Path = Path(__file__).resolve().parent
        for _ in range(6):
            candidate: Path = current / "pyproject.toml"
            if candidate.exists():
                pyproject_path = candidate
                break
            current = current.parent

    if not pyproject_path.exists():
        return playbooks

    try:
        with open(pyproject_path, "rb") as f:
            data: dict = tomllib.load(f)
        tool_data: dict = data.get("tool", {})
        pirlo_data: dict = tool_data.get("pirlo", {})
        playbooks = pirlo_data.get("playbooks", {})
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(
            f"Warning: Failed to load playbooks from pyproject.toml: {e}\n"
        )

    return playbooks


def load_all_playbooks() -> dict[str, PlaybookSpec]:
    """Discovers playbooks via AST scanning with pyproject.toml fallbacks."""
    specs: dict[str, PlaybookSpec] = {}

    # 1. AST Auto-Scan built-in & local workspace playbooks
    import pirlo

    pkg_playbooks_dir: Path = Path(pirlo.__file__).resolve().parent / "playbooks"
    specs.update(PlaybookScanner.scan_directory(pkg_playbooks_dir))

    cwd_playbooks_dir: Path = Path.cwd() / "playbooks"
    if cwd_playbooks_dir.exists() and cwd_playbooks_dir != pkg_playbooks_dir:
        specs.update(PlaybookScanner.scan_directory(cwd_playbooks_dir))

    # 2. Fallback: Pyproject.toml overrides for 3rd-party installed playbooks
    pyproject_playbooks: dict[str, str] = load_pyproject_playbooks()
    for name, entrypoint in pyproject_playbooks.items():
        if name not in specs:
            module_name: str
            class_name: str
            module_name, class_name = entrypoint.split(":")
            specs[name] = PlaybookSpec(
                name=name,
                description="",
                module_path=module_name,
                class_name=class_name,
                file_path=Path(),
            )

    return specs


def main() -> None:
    src_dir: str = str(Path(__file__).resolve().parents[4])
    cwd_dir: str = str(Path(__file__).resolve().parents[5])
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if cwd_dir not in sys.path:
        sys.path.insert(0, cwd_dir)

    specs: dict[str, PlaybookSpec] = load_all_playbooks()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: pirlo <command> [<args>]")
        print("\nAvailable commands:")
        print("  link          - Manage LLM links (API keys, base URLs)")
        print("  profile       - Manage browser profiles (list, delete)")
        print("  run           - Manage execution run history (list, show)")
        print("  connect       - Connect to remote pirlo serve instance")
        print("  disconnect    - Disconnect active remote pirlo serve session")
        print("  status        - Show active remote session health and links")
        if specs:
            command_name: str
            spec: PlaybookSpec
            for command_name, spec in sorted(specs.items()):
                desc_str: str = f" - {spec.description}" if spec.description else ""
                print(f"  {command_name:<13}{desc_str}")
        else:
            print("\nNo playbooks discovered.")

        print("\nFor help on a specific command, run:")
        print("  pirlo <command> --help")
        sys.exit(0)

    command: str = sys.argv[1]

    # Quick dispatch for built-in non-playbook subcommands
    if command in ("link", "profile", "run", "connect", "disconnect", "status"):
        if command == "link":
            from pirlo.infrastructure.adapters.cli.link_commands import (
                link_main,
            )

            try:
                link_main()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"Error: {e}\n")
                sys.exit(1)
            sys.exit(0)

        if command == "profile":
            from pirlo.infrastructure.adapters.cli.profile_commands import (
                profile_main,
            )

            try:
                profile_main()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"Error: {e}\n")
                sys.exit(1)
            sys.exit(0)

        if command == "run":
            from pirlo.infrastructure.adapters.cli.run_commands import (
                run_main,
            )

            try:
                run_main()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"Error: {e}\n")
                sys.exit(1)
            sys.exit(0)

        if command in ("connect", "disconnect", "status"):
            from pirlo.infrastructure.adapters.cli.connect_commands import (
                connect_main,
                disconnect_main,
                status_main,
            )

            try:
                if command == "connect":
                    connect_main()
                elif command == "disconnect":
                    disconnect_main()
                elif command == "status":
                    status_main()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"Error: {e}\n")
                sys.exit(1)
            sys.exit(0)

    target_playbook: str = (
        sys.argv[0].split(" ")[-1] if " " in sys.argv[0] else sys.argv[1]
    )
    if " " in sys.argv[0]:
        target_playbook = sys.argv[0].split(" ")[1]

    if target_playbook in specs:
        target_spec: PlaybookSpec = specs[target_playbook]
        try:
            local_src_dir: str = str(Path.cwd() / "src")
            local_cwd_dir: str = str(Path.cwd())
            if local_src_dir not in sys.path:
                sys.path.insert(0, local_src_dir)
            if local_cwd_dir not in sys.path:
                sys.path.insert(0, local_cwd_dir)

            module = importlib.import_module(target_spec.module_path)
            session_cls = getattr(module, target_spec.class_name)

            session_cls.cli(playbook_name=target_playbook)

        except Exception as e:  # noqa: BLE001
            sys.stderr.write(
                f"Error: Failed to load playbook '{target_playbook}' ({target_spec.module_path}:{target_spec.class_name}): {e}\n"
            )
            import traceback

            traceback.print_exc()
            sys.exit(1)
    else:
        sys.stderr.write(f"Error: Unknown command '{command}'\n")
        sys.stderr.write("Usage: pirlo <command> [<args>]\n")
        if specs:
            sys.stderr.write(f"Available commands: {', '.join(sorted(specs.keys()))}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
