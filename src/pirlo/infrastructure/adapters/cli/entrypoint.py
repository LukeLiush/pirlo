import importlib
import sys
import tomllib
from pathlib import Path


def load_playbooks() -> dict[str, str]:
    """Loads playbooks registered in pyproject.toml under [tool.pirlo.playbooks]."""
    playbooks: dict[str, str] = {}
    pyproject_path = Path.cwd() / "pyproject.toml"
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
    playbooks = load_playbooks()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: pirlo <command> [<args>]")
        print("\nAvailable commands:")
        print("  link          - Manage LLM links (API keys, base URLs)")
        print("  profile       - Manage browser profiles (list, delete)")
        if playbooks:
            # To show a nice description, we can dynamically load the classes and show their docstrings!
            for cmd, entrypoint in sorted(playbooks.items()):
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

                    sys.stderr.write(f"Error loading playbook command '{cmd}':\n")
                    traceback.print_exc()

                desc_str = f" - {description}" if description else ""
                print(f"  {cmd:<13}{desc_str}")
        else:
            print(
                "\nNo playbooks registered. Register them in pyproject.toml under [tool.pirlo.playbooks]"
            )

        print("\nFor help on a specific command, run:")
        print("  pirlo <command> --help")
        sys.exit(0)

    command = sys.argv[1]

    if command == "link":
        try:
            from pirlo.infrastructure.adapters.cli.link_commands import (
                link_main,
            )
            from pirlo.playbooks.autopass.providers import SUPPORTED_PROVIDERS

            link_main(SUPPORTED_PROVIDERS)
        except Exception as e:  # noqa: BLE001
            print(f"Error: Link management failed: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

    if command == "profile":
        try:
            from pirlo.infrastructure.adapters.cli.profile_commands import (
                profile_main,
            )

            profile_main()
        except Exception as e:  # noqa: BLE001
            print(f"Error: Profile management failed: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

    if command in playbooks:
        entrypoint = playbooks[command]
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

            # Reconstruct sys.argv for the subcommand
            # e.g., ['pirlo', 'login', '--profile', 'x'] -> ['pirlo login', '--profile', 'x']
            sys.argv = [f"pirlo {command}"] + sys.argv[2:]

            # Call the TerminalPitch cli runner
            session_cls.cli()
        except Exception as e:  # noqa: BLE001
            print(
                f"Error: Failed to load playbook '{command}' ({entrypoint}): {e}",
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
