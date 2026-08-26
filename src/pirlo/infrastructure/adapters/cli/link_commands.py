import argparse
import getpass
import sys
from pathlib import Path

from pirlo.core.models.link import SUPPORTED_PROVIDERS, LlmLink
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)
from pirlo.infrastructure.services.link_tester import LinkTester


def get_repo() -> JsonLinkRepository:
    filepath = Path("~/.pirlo-pitch/links.json").expanduser()
    return JsonLinkRepository(filepath)


def link_main(supported_providers: dict | None = None):
    if supported_providers is None:
        supported_providers = SUPPORTED_PROVIDERS

    parser = argparse.ArgumentParser(description="Manage LLM links.", prog="pirlo link")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. list
    subparsers.add_parser("list", help="List all active LLM links")

    # 2. create
    create_parser = subparsers.add_parser("create", help="Create or update an LLM link")
    create_parser.add_argument("name", nargs="?", help="Link Name")
    create_parser.add_argument(
        "--provider", help="Provider type (e.g. dashscope, gemini, openai, anthropic)"
    )
    create_parser.add_argument(
        "--model", help="LLM model (e.g. gemini-1.5-flash, qwen-turbo)"
    )
    create_parser.add_argument("--api-key", help="Provider API Key")
    create_parser.add_argument("--base-url", help="Override Base URL")
    create_parser.add_argument(
        "--test", action="store_true", help="Test connection after creation"
    )

    # 3. show
    show_parser = subparsers.add_parser("show", help="Show details of a specific link")
    show_parser.add_argument("name", help="Link Name")

    # 4. test
    test_parser = subparsers.add_parser(
        "test", help="Test connectivity of a specific link"
    )
    test_parser.add_argument("name", help="Link Name")

    # 5. delete
    delete_parser = subparsers.add_parser("delete", help="Delete a specific link")
    delete_parser.add_argument("name", help="Link Name")

    args = parser.parse_args(sys.argv[2:])
    repo = get_repo()

    if args.subcommand == "list":
        run_list(repo, supported_providers)
    elif args.subcommand == "create":
        run_create(repo, args, supported_providers)
    elif args.subcommand == "show":
        run_show(repo, args.name, supported_providers)
    elif args.subcommand == "test":
        run_test(repo, args.name)
    elif args.subcommand == "delete":
        run_delete(repo, args.name)


def run_list(repo: JsonLinkRepository, supported_providers: dict):
    links = repo.list_all()
    if not links:
        print("No active LLM links registered. Run 'pirlo link create' to add one.")
        return

    print("Active LLM Links:\n")
    print(f"{'Name':<20} {'Provider':<12} {'Model':<20} {'Base URL'}")
    print("─" * 90)
    for link in links:
        if link.base_url:
            base_url_str = link.base_url
        else:
            def_url = supported_providers.get(link.provider, {}).get("default_base_url")
            if def_url:
                base_url_str = f"Default ({def_url})"
            else:
                base_url_str = "Default (Official API)"

        if len(base_url_str) > 36:
            base_url_str = base_url_str[:33] + "..."
        print(f"{link.name:<20} {link.provider:<12} {link.model:<20} {base_url_str}")

    print("\n💡 Base URL Guide:")
    print(
        "   • Default: Automatically routes requests to the provider's official API endpoint."
    )
    print(
        "   • Custom:  Used for local models (Ollama, LM Studio), enterprise gateways, or proxies."
    )


def run_create(repo: JsonLinkRepository, args, supported_providers: dict):
    name = args._name
    provider = args.provider
    model = args.model
    api_key = args.api_key
    base_url = args.base_url
    test = args.test

    is_interactive = not (name and provider and model and api_key)

    if is_interactive:
        if not name:
            name = input("? Link Name: ").strip()
            if not name:
                print("Error: Link Name is required.")
                sys.exit(1)

        if not provider:
            print("? Select Provider:")
            choices = list(supported_providers.keys())
            for idx, choice in enumerate(choices, 1):
                print(f"  {idx}. {choice}")
            while True:
                try:
                    p_sel = input(f"Select choice (1-{len(choices)}): ").strip()
                    provider = choices[int(p_sel) - 1]
                    break
                except (ValueError, IndexError):
                    print("Invalid selection. Try again.")

        if not model:
            model = input(
                "? Input Model Name (required, e.g. gemini-1.5-flash, qwen-turbo): "
            ).strip()
            if not model:
                print("Error: Model Name is required.")
                sys.exit(1)

        if not api_key:
            api_key = getpass.getpass("? Input API Key: ").strip()
            if not api_key:
                print("Error: API Key is required.")
                sys.exit(1)

        if not base_url:
            default_url = supported_providers.get(provider, {}).get("default_base_url")
            default_info = (
                f"default: {default_url}"
                if default_url
                else "official provider endpoint"
            )
            base_url_input = input(
                f"? Input Base URL (optional - press ENTER to use {default_info}): "
            ).strip()
            base_url = base_url_input if base_url_input else None

        test_input = input("? Test connection now? [Y/n]: ").strip().lower()
        test = test_input in ("", "y", "yes")

    else:
        if provider not in supported_providers:
            print(
                f"Error: Invalid provider '{provider}'. Supported: {', '.join(supported_providers.keys())}"
            )
            sys.exit(1)
        if not model:
            print("Error: Model Name is required via --model flag.")
            sys.exit(1)

    link = LlmLink(
        name=name, provider=provider, model=model, api_key=api_key, base_url=base_url
    )

    if test:
        print(
            f"Checking connection to {provider.capitalize()} using model '{model}'..."
        )
        result = LinkTester.test_link(link)
        if result.success:
            print(f"[PASS] {result.message}")
        else:
            print(f"[FAIL] {result.message}")
            if is_interactive:
                save_anyway = input("Save link anyway? [y/N]: ").strip().lower()
                if save_anyway not in ("y", "yes"):
                    print("Aborted.")
                    sys.exit(1)

    repo.save(link)
    print(f"\nSuccessfully saved link '{name}'!")


def run_show(repo: JsonLinkRepository, name: str, supported_providers: dict):
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Link '{name}' not found.")
        sys.exit(1)

    print("Link Details:")
    print(f"  Name:        {link.name}")
    print(f"  Provider:    {link.provider}")
    print(f"  Model:       {link.model}")

    masked_key = link.api_key
    if len(masked_key) > 8:
        masked_key = masked_key[:4] + "*" * (len(masked_key) - 8) + masked_key[-4:]
    else:
        masked_key = "****"

    if link.base_url:
        base_url_display = f"{link.base_url} (Custom)"
    else:
        def_url = supported_providers.get(link.provider, {}).get("default_base_url")
        if def_url:
            base_url_display = f"Default ({def_url})"
        else:
            base_url_display = "Default (Official API)"

    print(f"  Base URL:    {base_url_display}")
    print(f"  API Key:     {masked_key}")


def run_test(repo: JsonLinkRepository, name: str):
    link = repo.get_by_name(name)
    if not link:
        print(f"Error: Link '{name}' not found.")
        sys.exit(1)

    target_endpoint = link.base_url or link.provider

    print(f"Testing link '{name}' to {target_endpoint} using model '{link.model}'...")
    result = LinkTester.test_link(link)
    if result.success:
        print(f"[PASS] {result.message}")
    else:
        print(f"[FAIL] {result.message}")
        sys.exit(1)


def run_delete(repo: JsonLinkRepository, name: str):
    if repo.delete(name):
        print(f"Successfully deleted link '{name}'.")
    else:
        print(f"Error: Link '{name}' not found.")
        sys.exit(1)
