import importlib
import json
import os
import shlex
import sqlite3
import sys
from pathlib import Path
from typing import Any

import flet as ft

from pirlo.cli import load_playbooks
from pirlo.core.models.run import RunCreateDTO
from pirlo.core.ports.pitch import Parameter
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.gui.controller import ConsoleController
from pirlo.infrastructure.adapters.storage.json_file_parameter_storage import (
    JsonFileParameterStorage,
)

# Resolve default PIRLO_WORKSPACE
PIRLO_WORKSPACE = Path(os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")).expanduser()


class PlaybookConsoleApp:
    """Main Flet application controller for the minimal Console UI (MVC refactored)."""

    def __init__(self, page: ft.Page, controller: ConsoleController):
        self.page = page
        self.controller = controller
        self.page.title = "Pirlo Console"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.bgcolor = "#f4f4f5"  # Light grey macOS background
        self.page.padding = 15

        # Standard window sizing
        self.page.window.width = 1100
        self.page.window.height = 750
        self.page.window.min_width = 800
        self.page.window.min_height = 600

        self.playbooks: dict[str, dict[str, Any]] = {}
        self.selected_playbook: str | None = None
        self.parameter_inputs: dict[str, tuple[str, ft.Control]] = {}

        # Pagination state
        self.runs_page = 0
        self.runs_per_page = 5
        self.log_page = 0
        self.log_lines_per_page = 100
        self.selected_run_id: str | None = None

        # UI Components
        self.playbook_list_view = ft.ListView(expand=True, spacing=5)
        self.config_form_container = ft.Column(
            spacing=15, scroll=ft.ScrollMode.AUTO, expand=True
        )
        self.submit_btn = ft.FilledButton(
            "Kickoff",
            icon=ft.Icons.PLAY_ARROW,
            bgcolor="#0066cc",  # Apple Blue
            color=ft.Colors.WHITE,
            on_click=lambda e: self.submit_command(),
        )

        # Merged Details & History Pane (Center Column)
        self.dynamic_pane_container = ft.Container(
            expand=True,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e4e4e7"),  # Zinc 200
            border_radius=8,
            padding=15,
        )

    def load_all_playbooks(self):
        """Loads registered playbooks dynamically from pyproject.toml."""
        raw_playbooks = load_playbooks()

        src_dir = str(Path.cwd() / "src")
        cwd_dir = str(Path.cwd())
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        if cwd_dir not in sys.path:
            sys.path.insert(0, cwd_dir)

        for name, entrypoint in raw_playbooks.items():
            try:
                module_name, class_name = entrypoint.split(":")
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)

                # Extract docstring
                doc = "No description available"
                if cls.__doc__:
                    doc_lines = [
                        line.strip()
                        for line in cls.__doc__.splitlines()
                        if line.strip()
                    ]
                    if doc_lines:
                        doc = doc_lines[0]

                # Introspect Parameters
                params = []
                for attr_name in sorted(dir(cls)):
                    attr_val = getattr(cls, attr_name)
                    if isinstance(attr_val, Parameter):
                        params.append(attr_val)

                self.playbooks[name] = {
                    "name": name,
                    "class": cls,
                    "doc": doc,
                    "parameters": params,
                    "entrypoint": entrypoint,
                }
            except Exception as e:  # noqa: BLE001
                print(
                    f"Warning: Failed to load playbook '{name}': {e}", file=sys.stderr
                )

    def build_ui(self):
        """Assembles the minimal layout: Left Sidebar, Center Log Pane, and Right Parameters."""
        self.load_all_playbooks()

        self.playbook_list_view.controls.clear()
        for name in sorted(self.playbooks.keys()):

            def make_handler(n):
                return lambda e: self.select_playbook(n)

            self.playbook_list_view.controls.append(
                ft.ListTile(
                    title=ft.Text(
                        name.upper(),
                        weight=ft.FontWeight.BOLD,
                        color="#09090b",
                        size=13,
                    ),
                    subtitle=ft.Text(
                        self.playbooks[name]["doc"], size=11, color="#71717a"
                    ),
                    leading=ft.Icon(ft.Icons.TERMINAL, color="#0066cc", size=18),
                    on_click=make_handler(name),
                    selected=(self.selected_playbook == name),
                    selected_tile_color="#d4d4d8",
                    shape=ft.RoundedRectangleBorder(radius=6),
                )
            )

        sidebar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "COMMANDS", size=12, weight=ft.FontWeight.BOLD, color="#71717a"
                    ),
                    ft.Divider(color="#e4e4e7", height=1),
                    self.playbook_list_view,
                ],
                spacing=10,
            ),
            width=220,
            bgcolor="#eaeaea",
            padding=15,
            border_radius=8,
        )

        right_sidebar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Parameters",
                        size=15,
                        weight=ft.FontWeight.BOLD,
                        color="#09090b",
                    ),
                    ft.Divider(color="#e4e4e7", height=1),
                    ft.Container(
                        content=self.config_form_container,
                        expand=True,
                    ),
                    ft.Divider(color="#e4e4e7", height=1),
                    ft.Row([self.submit_btn], alignment=ft.MainAxisAlignment.CENTER),
                ],
                spacing=10,
                expand=True,
            ),
            width=320,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e4e4e7"),
            border_radius=8,
            padding=15,
        )

        self.page.add(
            ft.Row(
                [sidebar, self.dynamic_pane_container, right_sidebar],
                expand=True,
                spacing=15,
            )
        )

        if self.playbooks:
            first_name = min(self.playbooks.keys())
            self.select_playbook(first_name)

    def select_playbook(self, name: str):
        """Switches the view to the selected subcommand."""
        self.selected_playbook = name

        # Update sidebar selection highlight
        for tile in self.playbook_list_view.controls:
            if isinstance(tile, ft.ListTile) and isinstance(tile.title, ft.Text):
                tile.selected = tile.title.value.lower() == name
        self.playbook_list_view.update()

        # Build form inputs
        self.config_form_container.controls.clear()
        self.parameter_inputs.clear()

        pb_data = self.playbooks[name]
        saved_params = self.load_saved_parameters(name)

        grid_controls: list[ft.Control] = []
        for param in pb_data["parameters"]:
            label = param.name.replace("_", " ").capitalize()
            help_text = param.help or ""
            val = saved_params.get(param.name, param.default)

            if param.type_func == bool:
                sw = ft.Switch(
                    label=label,
                    value=bool(val),
                    tooltip=help_text,
                    active_color="#0066cc",
                )
                self.parameter_inputs[param.name] = ("bool", sw)
                grid_controls.append(sw)
            elif param.type_func == list[str]:
                initial_val = ",".join(val) if isinstance(val, list) else str(val or "")
                tf = ft.TextField(
                    label=label,
                    value=initial_val,
                    helper=f"List of values (comma-separated). {help_text}",
                    border_color="#d4d4d8",
                    focused_border_color="#0066cc",
                    text_size=13,
                    color="#09090b",
                    label_style=ft.TextStyle(color="#71717a", size=12),
                    helper_style=ft.TextStyle(color="#71717a", size=11),
                )
                self.parameter_inputs[param.name] = ("list[str]", tf)
                grid_controls.append(tf)
            else:
                tf = ft.TextField(
                    label=label,
                    value=str(val) if val is not None else "",
                    helper=help_text,
                    border_color="#d4d4d8",
                    focused_border_color="#0066cc",
                    text_size=13,
                    color="#09090b",
                    label_style=ft.TextStyle(color="#71717a", size=12),
                    helper_style=ft.TextStyle(color="#71717a", size=11),
                )
                self.parameter_inputs[param.name] = ("str", tf)
                grid_controls.append(tf)

        # Layout parameters directly in a scrollable single column
        for c in grid_controls:
            self.config_form_container.controls.append(
                ft.Container(content=c, padding=ft.Padding.only(bottom=5))
            )
        self.config_form_container.update()

        # Reset pagination for runs
        self.runs_page = 0
        # Show Runs History by default
        self.show_runs_history()

    def load_saved_parameters(self, subcommand: str) -> dict[str, Any]:
        """Loads previously saved parameters (presets) from workspace using ParameterStorage."""
        params = self.controller.parameter_storage.load_parameters(
            f"{subcommand}_subcommand.json"
        )
        if not params:
            # Fallback to the old workspace folder structure if it exists
            old_path = PIRLO_WORKSPACE / subcommand / "subcommand.json"
            if old_path.exists():
                try:
                    with open(old_path, "r", encoding="utf-8") as f:
                        params = json.load(f)
                except Exception:  # noqa: BLE001, S110
                    pass
        return params

    def save_parameters(self, subcommand: str, params: dict[str, Any]):
        """Saves edited parameters (presets) using ParameterStorage."""
        self.controller.parameter_storage.save_parameters(
            f"{subcommand}_subcommand.json", params
        )

    def change_runs_page(self, delta: int):
        """Changes the current runs history page and updates view."""
        self.runs_page += delta
        self.show_runs_history()

    def show_runs_history(self):
        """Displays the paginated, sorted table of historical runs from SQLite database."""
        if not self.selected_playbook:
            return

        rows = []
        runs, total_pages = self.controller.get_runs_history(
            self.selected_playbook, self.runs_page, self.runs_per_page
        )
        self.runs_page = max(0, min(self.runs_page, total_pages - 1))

        for run in runs:
            run_id = run.run_id
            status = run.status.value.upper()

            # Format times, converting UTC to local timezone
            if run.started_at:
                try:
                    started_dt = run.started_at.astimezone()
                except (ValueError, TypeError):
                    started_dt = run.started_at
                started_at_str = started_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                started_at_str = "—"

            if run.finished_at:
                try:
                    finished_dt = run.finished_at.astimezone()
                except (ValueError, TypeError):
                    finished_dt = run.finished_at
                finished_at_str = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                finished_at_str = "—"

            try:
                updated_dt = run.updated_at.astimezone()
            except (ValueError, TypeError):
                updated_dt = run.updated_at
            updated_at_str = updated_dt.strftime("%Y-%m-%d %H:%M:%S")

            # Color badge
            color = "#71717a"  # Not started
            if status == "COMPLETED":
                color = "#16a34a"  # Completed
            elif status == "STARTED":
                color = "#2563eb"  # Running/Started

            badge = ft.Container(
                content=ft.Text(
                    status,
                    size=11,
                    color=ft.Colors.WHITE,
                    weight=ft.FontWeight.BOLD,
                ),
                bgcolor=color,
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                border_radius=4,
            )

            def make_click_handler(rid):
                return lambda e: self.show_run_details(rid)

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Container(
                                content=ft.Text(
                                    run_id,
                                    weight=ft.FontWeight.BOLD,
                                    color="#0066cc",
                                    size=12,
                                ),
                                on_click=make_click_handler(run_id),
                            )
                        ),
                        ft.DataCell(badge),
                        ft.DataCell(ft.Text(started_at_str, size=11, color="#09090b")),
                        ft.DataCell(ft.Text(finished_at_str, size=11, color="#09090b")),
                        ft.DataCell(ft.Text(updated_at_str, size=11, color="#09090b")),
                    ]
                )
            )

        if not rows:
            table_content = ft.Container(
                content=ft.Text("No execution history found.", color="#71717a"),
                alignment=ft.alignment.Alignment(0, 0),
                padding=20,
            )
            pagination_row = ft.Container()
        else:
            table_content = ft.DataTable(
                columns=[
                    ft.DataColumn(
                        ft.Text("Run ID", weight=ft.FontWeight.BOLD, color="#09090b")
                    ),
                    ft.DataColumn(
                        ft.Text("Status", weight=ft.FontWeight.BOLD, color="#09090b")
                    ),
                    ft.DataColumn(
                        ft.Text(
                            "Started At", weight=ft.FontWeight.BOLD, color="#09090b"
                        )
                    ),
                    ft.DataColumn(
                        ft.Text(
                            "Finished At", weight=ft.FontWeight.BOLD, color="#09090b"
                        )
                    ),
                    ft.DataColumn(
                        ft.Text(
                            "Updated At", weight=ft.FontWeight.BOLD, color="#09090b"
                        )
                    ),
                ],
                rows=rows,
                column_spacing=25,
                heading_row_height=35,
                data_row_min_height=30,
            )

            prev_btn = ft.IconButton(
                icon=ft.Icons.NAVIGATE_BEFORE,
                on_click=lambda e: self.change_runs_page(-1),
                disabled=(self.runs_page == 0),
            )
            next_btn = ft.IconButton(
                icon=ft.Icons.NAVIGATE_NEXT,
                on_click=lambda e: self.change_runs_page(1),
                disabled=(self.runs_page >= total_pages - 1),
            )
            page_info = ft.Text(
                f"Page {self.runs_page + 1} of {total_pages}", size=12, color="#71717a"
            )

            pagination_row = ft.Row(
                [prev_btn, page_info, next_btn],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            )

        self.dynamic_pane_container.content = ft.Column(
            [
                ft.Text(
                    "RUNS HISTORY", size=14, weight=ft.FontWeight.BOLD, color="#09090b"
                ),
                ft.Divider(color="#e4e4e7", height=1),
                table_content,
                pagination_row,
            ],
            spacing=15,
        )
        self.dynamic_pane_container.update()

    def change_log_page(self, delta: int):
        """Changes the current log line page and updates view."""
        self.log_page += delta
        if self.selected_run_id:
            self.show_run_details(self.selected_run_id)

    def show_run_details(self, run_id: str):
        """Displays paginated static terminal logs for a run, along with parameter specs and a Back button."""
        if self.selected_run_id != run_id:
            self.selected_run_id = run_id
            self.log_page = 0

        run = self.controller.run_repository.get_by_id(run_id)
        if not run:
            lines = [f"[ERROR] Run {run_id} not found in database.\n"]
            params = {}
        else:
            lines = self.controller.read_run_logs(run)
            params = self.controller.read_run_parameters(run)

        total_log_pages = max(
            1, (len(lines) + self.log_lines_per_page - 1) // self.log_lines_per_page
        )
        self.log_page = max(0, min(self.log_page, total_log_pages - 1))

        start_idx = self.log_page * self.log_lines_per_page
        end_idx = min(len(lines), (self.log_page + 1) * self.log_lines_per_page)
        page_lines = lines[start_idx:end_idx]

        log_view = ft.ListView(expand=True, spacing=2)
        for line in page_lines:
            self.append_line_to_view(log_view, line)

        prev_log_btn = ft.IconButton(
            icon=ft.Icons.NAVIGATE_BEFORE,
            on_click=lambda e: self.change_log_page(-1),
            disabled=(self.log_page == 0),
        )
        next_log_btn = ft.IconButton(
            icon=ft.Icons.NAVIGATE_NEXT,
            on_click=lambda e: self.change_log_page(1),
            disabled=(self.log_page >= total_log_pages - 1),
        )
        log_page_info = ft.Text(
            f"Showing lines {start_idx + 1}-{end_idx} of {len(lines)} (Page {self.log_page + 1}/{total_log_pages})",
            size=12,
            color="#71717a",
        )

        log_pagination_row = ft.Row(
            [prev_log_btn, log_page_info, next_log_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        )

        # Format parameters display under the title
        param_chips: list[ft.Control] = []
        if params:
            for k, v in params.items():
                param_chips.append(
                    ft.Container(
                        content=ft.Text(f"{k}: {v}", size=11, color="#374151"),
                        bgcolor="#f3f4f6",
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    )
                )
        params_info_row = ft.Row(
            param_chips
            if param_chips
            else [ft.Text("No parameters configuration used.", size=11, italic=True)],
            wrap=True,
            spacing=5,
        )

        self.dynamic_pane_container.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            f"RUN DETAILS: {run_id}",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color="#09090b",
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            tooltip="Back to History",
                            on_click=lambda e: self.show_runs_history(),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                params_info_row,
                ft.Divider(color="#e4e4e7", height=1),
                ft.Container(
                    content=log_view,
                    bgcolor="#f8fafc",
                    border=ft.Border.all(1, "#e4e4e7"),
                    padding=10,
                    border_radius=5,
                    expand=True,
                ),
                log_pagination_row,
            ],
            spacing=10,
        )
        self.dynamic_pane_container.update()

    def append_line_to_view(
        self, log_view: ft.ListView, line: str, is_error: bool = False
    ):
        """Appends a line of text to the given log view with appropriate colors."""
        line = line.rstrip("\n")
        color = "#334155"  # Slate 700 default

        if is_error or "[ERROR]" in line or "Traceback" in line or "RED CARD" in line:
            color = "#dc2626"
        elif "[WARNING]" in line or "YELLOW CARD" in line:
            color = "#d97706"
        elif "[INFO]" in line or "GOAL!" in line or "[SUCCESS]" in line:
            color = "#16a34a"

        log_view.controls.append(
            ft.Text(line, font_family="monospace", size=12, color=color)
        )

    def submit_command(self):
        """Saves parameters, generates metadata, and opens external macOS Terminal executing subcommand."""
        playbook_name = self.selected_playbook
        if not playbook_name:
            return

        # Gather parameter inputs
        raw_params = {}

        for param_name, (ptype, control) in self.parameter_inputs.items():
            if ptype == "bool":
                assert isinstance(control, ft.Switch)
                val = bool(control.value)
                raw_params[param_name] = val
            elif ptype == "list[str]":
                assert isinstance(control, ft.TextField)
                txt = control.value.strip() if control.value else ""
                val = (
                    [item.strip() for item in txt.split(",") if item.strip()]
                    if txt
                    else []
                )
                raw_params[param_name] = val
            else:
                assert isinstance(control, ft.TextField)
                val = control.value.strip() if control.value else ""
                raw_params[param_name] = val

        # Save configuration parameters as preset
        self.save_parameters(playbook_name, raw_params)

        # Kickoff the execution run via controller MVC
        dto = RunCreateDTO(playbook=playbook_name, parameters=raw_params)
        run = self.controller.kickoff_run(dto)

        # Retrieve absolute locations to feed to Terminal command
        param_abs_path = run.get_parameter_location(self.controller.workspace)
        log_abs_path = run.get_log_location(self.controller.workspace)

        # Ensure directory for logs exists prior to tee execution
        log_abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Pipe command utilizing custom tee utility module under the new Onion adapters directory layout
        cmd_str = f"cd {shlex.quote(str(Path.cwd()))} && PYTHONPATH=src .venv/bin/python -m pirlo.cli {playbook_name} --config {shlex.quote(str(param_abs_path))} --run-id {run.run_id} 2>&1 | .venv/bin/python -m pirlo.infrastructure.adapters.cli.tee {shlex.quote(str(log_abs_path))}"

        # Escape command string for AppleScript double-quoted string
        escaped_cmd_str = cmd_str.replace("\\", "\\\\").replace('"', '\\"')

        # AppleScript command
        applescript = f'''
        tell application "Terminal"
            do script "{escaped_cmd_str}"
            activate
        end tell
        '''
        try:
            import subprocess

            subprocess.Popen(["osascript", "-e", applescript])

            # Show a message in the dynamic pane
            self.dynamic_pane_container.content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                f"RUN DETAILS: {run.run_id}",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color="#09090b",
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ARROW_BACK,
                                tooltip="Back to History",
                                on_click=lambda e: self.show_runs_history(),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(color="#e4e4e7", height=1),
                    ft.Container(
                        content=ft.Text(
                            f"[INFO] Launched command in external OS Terminal:\n\n{cmd_str}",
                            font_family="monospace",
                            size=12,
                            color="#16a34a",
                        ),
                        bgcolor="#f8fafc",
                        border=ft.Border.all(1, "#e4e4e7"),
                        padding=15,
                        border_radius=5,
                        expand=True,
                    ),
                ],
                spacing=10,
            )
            self.dynamic_pane_container.update()
        except Exception as e:  # noqa: BLE001
            self.page.show_snack_bar(
                ft.SnackBar(content=ft.Text(f"Failed to launch OS Terminal: {e}"))
            )


def run_console(web: bool = False, port: int = 8550):
    """Entry point to launch the Flet Console App."""

    def main_app(page: ft.Page):
        # Establish connection for SQLite run history
        db_path = PIRLO_WORKSPACE / "pirlo.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)

        # Construct Ports & Adapters
        run_repo = SqliteRunHistoryRepository(conn)
        param_storage = JsonFileParameterStorage(PIRLO_WORKSPACE)

        # Instantiate Controller
        controller = ConsoleController(PIRLO_WORKSPACE, run_repo, param_storage)

        app = PlaybookConsoleApp(page, controller)
        app.build_ui()

    if web:
        ft.app(target=main_app, port=port, view=ft.AppView.WEB_BROWSER)
    else:
        ft.app(target=main_app)
