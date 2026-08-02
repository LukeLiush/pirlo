import argparse
import sys
from datetime import datetime, timezone

from pirlo.core.services.profile_manager import ProfileManager


def profile_main():
    parser = argparse.ArgumentParser(
        description="Manage browser profiles.", prog="pirlo profile"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. list
    subparsers.add_parser("list", help="List all saved browser profiles")

    # 2. delete
    delete_parser = subparsers.add_parser(
        "delete", help="Delete a specific browser profile"
    )
    delete_parser.add_argument("name", help="Profile Name")

    args = parser.parse_args(sys.argv[2:])

    if args.subcommand == "list":
        run_list()
    elif args.subcommand == "delete":
        run_delete(args.name)


def format_expires_in(expires_at_str: str) -> str:
    if not expires_at_str:
        return "N/A"
    try:
        expires_dt = datetime.fromisoformat(expires_at_str)
        now = datetime.now(timezone.utc)
        if now >= expires_dt:
            return "Expired"
        delta = expires_dt - now
        days = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            return f"{days}d {hours}h left"
        elif hours > 0:
            return f"{hours}h left"
        else:
            mins = max(1, delta.seconds // 60)
            return f"{mins}m left"
    except Exception:  # noqa: BLE001
        return "N/A"


def run_list():
    profiles = ProfileManager.list_profiles()
    if not profiles:
        print("No browser profiles found. Run 'pirlo login' to create one.")
        return

    print("Saved Browser Profiles:\n")
    print(
        f"{'Profile Name':<18} {'Expires In':<16} {'Authenticated Portals / URLs'}"
    )
    print("─" * 90)

    for meta in profiles:
        expires_in_str = format_expires_in(meta.expires_at)

        urls = meta.authenticated_urls or []
        if not urls:
            url_display_lines = ["(None)"]
        else:
            url_display_lines = [f"• {u}" for u in urls]

        # Print first line with profile info
        first_url = url_display_lines[0]
        print(
            f"{meta.name:<18} {expires_in_str:<16} {first_url}"
        )

        # Print remaining URL lines wrapped under the same column
        for sub_url in url_display_lines[1:]:
            print(f"{'':<18} {'':<16} {sub_url}")
    print()


def run_delete(name: str):
    if ProfileManager.delete_profile(name):
        print(f"Successfully deleted profile '{name}'.")
    else:
        print(f"Error: Profile '{name}' not found.")
        sys.exit(1)
