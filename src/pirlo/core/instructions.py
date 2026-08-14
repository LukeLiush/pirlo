from dataclasses import dataclass


@dataclass
class Instruction:
    message: str
    detail: str | None = None

    def format(self, **kwargs) -> "Instruction":
        return Instruction(
            message=self.message.format(**kwargs),
            detail=self.detail.format(**kwargs) if self.detail else None,
        )


class AutopassInstructions:
    TASK_REQUIRED = Instruction(
        message="Task prompt is required",
        detail=(
            "Please provide a task prompt using the --task parameter or by setting it in your playbook configuration.\n\n"
            "Example:\n"
            "  pirlo autopass --task \"go to google.com and search for 'openai'\""
        ),
    )
    PROFILE_MISSING = Instruction(
        message="Browser profile '{profile}' missing or not initialized",
        detail=(
            "The specified browser profile '{profile}' was not found.\n"
            "{existing_info}\n"
            "To create and authenticate this profile, please run:\n"
            "  pirlo login --profile {profile} --urls <target_urls>"
        ),
    )
    PROFILE_EXPIRED = Instruction(
        message="Browser profile '{profile}' session has expired",
        detail=(
            "The browser profile session '{profile}' has expired (expired on {expires_at}, {days_expired} ago).\n"
            "To regenerate and refresh this session, please re-authenticate:\n"
            "  pirlo login --profile {profile} --urls {authenticated_urls}"
        ),
    )


class LoginInstructions:
    LINK_PATH_NOT_FOUND = Instruction(
        message="Link path not found",
        detail="The specified file '{path}' does not exist.",
    )
    URLS_REQUIRED = Instruction(
        message="No URLs to open",
        detail=(
            "Please provide at least one target URL. You can:\n"
            "  1. Pass URLs directly using [bold]--links[/bold] (e.g., --links https://github.com)\n"
            "  2. Pass a text file with URLs using [bold]--link-path[/bold] (e.g., --link-path urls.txt)\n\n"
            "Example:\n"
            "  [cyan] uv run pirlo login --links https://github.com https://google.com[/cyan]"
        ),
    )
