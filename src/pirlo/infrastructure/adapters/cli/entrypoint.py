import contextlib
import importlib
import sys
import tomllib
from pathlib import Path

from pirlo.infrastructure.services.play_scanner import (
    PlayScanner,
    PlaySpec,
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


def load_all_playbooks() -> dict[str, PlaySpec]:
    """Discovers playbooks via AST scanning across built-in, local src, workspace, and installed packages."""
    specs: dict[str, PlaySpec] = {}

    # 1. AST Auto-Scan built-in playbooks
    with contextlib.suppress(Exception):
        import pirlo

        pkg_playbooks_dir: Path = Path(pirlo.__file__).resolve().parent / "playbooks"
        if pkg_playbooks_dir.exists():
            specs.update(PlayScanner.scan_directory(pkg_playbooks_dir))

    # 2. Local current working directory (src/ and playbooks/)
    cwd_src: Path = Path.cwd() / "src"
    if cwd_src.exists():
        specs.update(PlayScanner.scan_directory(cwd_src))

    cwd_playbooks_dir: Path = Path.cwd() / "playbooks"
    if cwd_playbooks_dir.exists():
        specs.update(PlayScanner.scan_directory(cwd_playbooks_dir))

    # 3. Workspace path
    with contextlib.suppress(Exception):
        from pirlo.core.config import get_workspace_path

        workspace_path = get_workspace_path()
        if (workspace_path / "src").exists():
            specs.update(PlayScanner.scan_directory(workspace_path / "src"))
        if (workspace_path / "playbooks").exists():
            specs.update(PlayScanner.scan_directory(workspace_path / "playbooks"))

    # 4. Any installed pirlo_* packages in sys.path
    for p in sys.path:
        p_path = Path(p)
        if p_path.exists() and p_path.is_dir():
            with contextlib.suppress(Exception):
                for candidate in p_path.glob("pirlo_*"):
                    if candidate.is_dir() and not candidate.name.endswith(".dist-info"):
                        specs.update(PlayScanner.scan_directory(candidate))

    # 5. Fallback: Pyproject.toml overrides for 3rd-party installed playbooks
    pyproject_playbooks: dict[str, str] = load_pyproject_playbooks()
    for name, entrypoint in pyproject_playbooks.items():
        if name not in specs:
            module_name: str
            class_name: str
            module_name, class_name = entrypoint.split(":")
            specs[name] = PlaySpec(
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

    # Ensure local cwd and cwd/src are in sys.path
    local_src: str = str(Path.cwd() / "src")
    if Path(local_src).exists() and local_src not in sys.path:
        sys.path.insert(0, local_src)
    local_cwd: str = str(Path.cwd())
    if local_cwd not in sys.path:
        sys.path.insert(0, local_cwd)

    specs: dict[str, PlaySpec] = load_all_playbooks()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: pirlo <command> [<args>]")
        print("\nAvailable commands:")
        print("  link          - Manage LLM links (API keys, base URLs)")
        print("  orchestrator  - Manage orchestrator links (Prefect, Airflow)")
        print("  profile       - Manage browser profiles (list, delete)")
        print("  run           - Manage execution run history (list, show)")
        if specs:
            command_name: str
            spec: PlaySpec
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
    if command in ("link", "orchestrator", "profile", "run"):
        if command == "orchestrator":
            from pirlo.infrastructure.adapters.cli.orchestrator_commands import (
                orchestrator_main,
            )

            try:
                orchestrator_main()
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"Error: {e}\n")
                sys.exit(1)
            sys.exit(0)

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

    target_play_name: str = (
        sys.argv[0].split(" ")[-1] if " " in sys.argv[0] else sys.argv[1]
    )
    if " " in sys.argv[0]:
        target_play_name = sys.argv[0].split(" ")[1]

    if target_play_name in specs:
        target_spec: PlaySpec = specs[target_play_name]
        try:
            local_src_dir: str = str(Path.cwd() / "src")
            local_cwd_dir: str = str(Path.cwd())
            if local_src_dir not in sys.path:
                sys.path.insert(0, local_src_dir)
            if local_cwd_dir not in sys.path:
                sys.path.insert(0, local_cwd_dir)
            from pirlo.infrastructure.services.log_streamer import (
                setup_pirlo_logging,
            )

            show_logs: bool = any(arg in sys.argv for arg in ("-l", "--log"))
            setup_pirlo_logging(show_logs=show_logs)

            module = importlib.import_module(target_spec.module_path)
            session_cls = getattr(module, target_spec.class_name)

            session_cls.cli(play_name=target_play_name)

        except Exception as e:  # noqa: BLE001
            sys.stderr.write(
                f"Error: Failed to load playbook '{target_play_name}' ({target_spec.module_path}:{target_spec.class_name}): {e}\n"
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
