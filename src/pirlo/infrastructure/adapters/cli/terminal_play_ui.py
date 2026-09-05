# src/pirlo/infrastructure/adapters/cli/terminal_play_ui.py
from __future__ import annotations

import asyncio
import getpass
from contextlib import AbstractContextManager
from datetime import UTC
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pirlo.core.ports.play_ui import PlayUI


class TerminalPlayUI(PlayUI):
    """Rich graphical terminal presentation adapter for Play."""

    COLOR_PALETTE: tuple[str, ...] = (
        "cyan",
        "magenta",
        "yellow",
        "bright_blue",
        "green",
        "bright_magenta",
        "bright_cyan",
    )

    def __init__(
        self,
        play_name: str | None = None,
        console: Console | None = None,
    ) -> None:
        self._play_name: str | None = play_name
        self._console = console or Console()
        if play_name:
            idx = abs(hash(play_name)) % len(self.COLOR_PALETTE)
            self._color: str = self.COLOR_PALETTE[idx]
        else:
            self._color = "cyan"

    @property
    def console(self) -> Console:
        return self._console

    @property
    def play_name(self) -> str | None:
        return self._play_name

    def _timestamp(self) -> str:
        from datetime import datetime

        return datetime.now(UTC).astimezone().strftime("%H:%M:%S")

    def _format_badge(self) -> str:
        from rich.markup import escape

        ts = f"[dim]{self._timestamp()}[/dim]"
        if self._play_name:
            badge = escape(f"[{self._play_name}]")
            return f"{ts} [bold {self._color}]{badge}[/bold {self._color}]"
        return ts

    def header(self, title: str, subtitle: str | None = None) -> None:
        from rich.markup import escape

        panel_title = (
            f"[bold {self._color}]{escape(f'[{self._play_name}]')}[/bold {self._color}]"
            if self._play_name
            else None
        )
        text = f"[bold green]{title}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self._console.print(
            Panel(text, title=panel_title, expand=False, border_style=self._color)
        )

    def status(self, message: str) -> AbstractContextManager[Any]:
        from rich.markup import escape

        badge = f"{escape(f'[{self._play_name}]')} " if self._play_name else ""
        return self._console.status(
            f"[bold {self._color}]{badge}{message}[/bold {self._color}]",
            spinner="dots",
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
        badge = self._format_badge()
        text = f"{badge} 🎙️ [{self._color}]{message}[/{self._color}]"
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
        from rich.markup import escape

        panel_title = (
            f"⚽ [bold {self._color}]{escape(f'[{self._play_name}]')}[/bold {self._color}]"
            if self._play_name
            else None
        )
        text = f"[bold green]⚽ GOAL! {message}[/bold green]"
        if detail:
            text += f"\n[{self._color}]{detail}[/{self._color}]"
        self._console.print(
            Panel(
                text,
                title=panel_title,
                border_style="green",
                expand=False,
            )
        )

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
