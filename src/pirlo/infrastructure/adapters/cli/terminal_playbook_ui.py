import asyncio
import getpass
from contextlib import AbstractContextManager
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pirlo.core.ports.playbook_ui import PlaybookUI


class TerminalPlaybookUI(PlaybookUI):
    """Rich graphical terminal presentation adapter for Playbook."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    @property
    def console(self) -> Console:
        return self._console

    def header(self, title: str, subtitle: str | None = None) -> None:
        text = f"[bold green]{title}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self._console.print(Panel(text, expand=False, border_style="cyan"))

    def status(self, message: str) -> AbstractContextManager[Any]:
        return self._console.status(
            f"[bold green]{message}[/bold green]", spinner="dots"
        )

    def lineup(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        tbl = Table(
            title=title,
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
        )
        for col in columns:
            tbl.add_column(col)
        for row in rows:
            tbl.add_row(*row)
        self._console.print(tbl)

    def commentary(self, message: str, detail: str | None = None) -> None:
        text = f"[cyan]🎙️ {message}[/cyan]"
        if detail:
            text += f"\n  [dim]{detail}[/dim]"
        self._console.print(text)

    async def var_check(self, message: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, input, f"🔍 [VAR CHECK] {message}: ")

    async def prompt_password(self, prompt_message: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, getpass.getpass, f"🔑 {prompt_message}: "
        )

    def goal(self, message: str, detail: str | None = None) -> None:
        text = f"⚽ [bold green]GOAL! {message}[/bold green]"
        if detail:
            text += f"\n[cyan]{detail}[/cyan]"
        self._console.print(Panel(text, border_style="green", expand=False))

    def red_card(self, message: str, detail: str | None = None) -> None:
        text = f"🟥 [bold red]RED CARD! {message}[/bold red]"
        if detail:
            text += f"\n[dim]{detail}[/dim]"
        self._console.print(Panel(text, border_style="red", expand=False))

    def yellow_card(self, message: Any, detail: str | None = None) -> None:
        if hasattr(message, "message"):
            msg_str = message.message
            det_str = getattr(message, "detail", detail)
        else:
            msg_str = str(message)
            det_str = detail

        text = f"🟨 [bold yellow]YELLOW CARD: {msg_str}[/bold yellow]"
        if det_str:
            text += f"\n[dim]{det_str}[/dim]"
        self._console.print(Panel(text, border_style="yellow", expand=False))


TerminalPitchUI = TerminalPlaybookUI
