import importlib
import sys
import tomllib
from pathlib import Path


def load_playbooks() -> dict[str, str]:
    """Loads playbooks registered in pyproject.toml under [tool.pirlo.playbooks]."""
    playbooks: dict[str, str] = {}
    pyproject_path = Path.cwd() / "pyproject.toml"
    if not pyproject_path.exists():
        current = Path(__file__).resolve().parent
        for _ in range(6):
            candidate = current / "pyproject.toml"
            if candidate.exists():
                pyproject_path = candidate
                break
            current = current.parent

    if not pyproject_path.exists():
        return playbooks

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        tool_data = data.get("tool", {})
        pirlo_data = tool_data.get("pirlo", {})
        playbooks = pirlo_data.get("playbooks", {})
    except Exception as e:  # noqa: BLE001
        print(
            f"Warning: Failed to load playbooks from pyproject.toml: {e}",
            file=sys.stderr,
        )

    return playbooks


def main():
    src_dir = str(Path(__file__).resolve().parents[4])
    cwd_dir = str(Path(__file__).resolve().parents[5])
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if cwd_dir not in sys.path:
        sys.path.insert(0, cwd_dir)

    playbooks: dict[str, str] = load_playbooks()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: pirlo <command> [<args>]")
        print("\nAvailable commands:")
        print("  link          - Manage LLM links (API keys, base URLs)")
        print("  profile       - Manage browser profiles (list, delete)")
        print("  run           - Manage execution run history (list, show)")
        if playbooks:
            # To show a nice description, we can dynamically load the classes and show their docstrings!
            for command, entrypoint in sorted(playbooks.items()):
                description = ""
                try:
                    module_name, class_name = entrypoint.split(":")
                    # Temporarily add src/ and current dir to path to find local modules
                    src_dir = str(Path.cwd() / "src")
                    cwd_dir = str(Path.cwd())
                    sys_path_added = []
                    if src_dir not in sys.path:
                        sys.path.insert(0, src_dir)
                        sys_path_added.append(src_dir)
                    if cwd_dir not in sys.path:
                        sys.path.insert(0, cwd_dir)
                        sys_path_added.append(cwd_dir)

                    module = importlib.import_module(module_name)
                    cls = getattr(module, class_name)
                    if cls.__doc__:
                        description = cls.__doc__.strip().split("\n")[0]

                    for path in sys_path_added:
                        sys.path.remove(path)
                except Exception:  # noqa: BLE001
                    import traceback

                    sys.stderr.write(f"Error loading playbook command '{command}':\n")
                    traceback.print_exc()

                desc_str = f" - {description}" if description else ""
                print(f"  {command:<13}{desc_str}")
        else:
            print(
                "\nNo playbooks registered. Register them in pyproject.toml under [tool.pirlo.playbooks]"
            )

        print("\nFor help on a specific command, run:")
        print("  pirlo <command> --help")
        sys.exit(0)

    command = sys.argv[1]

    # Quick dispatch for built-in non-playbook subcommands (e.g. link, profile, run)
    # TODO, i need to turn it into config.
    if command in ("link", "profile", "run"):
        if command == "link":
            from pirlo.infrastructure.adapters.cli.link_commands import (
                link_main,
            )

            try:
                link_main()
            except Exception as e:  # noqa: BLE001
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)

        if command == "profile":
            from pirlo.infrastructure.adapters.cli.profile_commands import (
                profile_main,
            )

            try:
                profile_main()
            except Exception as e:  # noqa: BLE001
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)

        if command == "run":
            from pirlo.infrastructure.adapters.cli.run_commands import (
                run_main,
            )

            try:
                run_main()
            except Exception as e:  # noqa: BLE001
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)

    target_playbook = sys.argv[0].split(" ")[-1] if " " in sys.argv[0] else sys.argv[1]
    if " " in sys.argv[0]:
        target_playbook = sys.argv[0].split(" ")[1]

    if target_playbook in playbooks:
        entrypoint = playbooks[target_playbook]
        try:
            module_name, class_name = entrypoint.split(":")
            # Ensure src/ and current directory are in sys.path so the local playbook package can be resolved
            src_dir = str(Path.cwd() / "src")
            cwd_dir = str(Path.cwd())
            if src_dir not in sys.path:
                sys.path.insert(0, src_dir)
            if cwd_dir not in sys.path:
                sys.path.insert(0, cwd_dir)

            module = importlib.import_module(module_name)
            session_cls = getattr(module, class_name)

            # Call the TerminalPitch cli runner
            session_cls.cli(playbook_name=target_playbook)

        except Exception as e:  # noqa: BLE001
            print(
                f"Error: Failed to load playbook '{target_playbook}' ({entrypoint}): {e}",
                file=sys.stderr,
            )
            import traceback

            traceback.print_exc()
            sys.exit(1)
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Usage: pirlo <command> [<args>]", file=sys.stderr)
        if playbooks:
            print(
                f"Available commands: {', '.join(sorted(playbooks.keys()))}",
                file=sys.stderr,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
