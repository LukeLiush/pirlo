import contextlib
import inspect
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prefect import flow, task

from pirlo.core.config import get_workspace_path
from pirlo.core.models.browser_config import BrowserConfig
from pirlo.core.models.run import Run, RunStatus
from pirlo.core.ports.orchestrator import AutopassExecutionOptions, TaskOrchestrator
from pirlo.core.ports.pitch import Parameter, Pitch
from pirlo.core.services.run_id_generator import generate_task_id
from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    DefaultBrowserAgentFactory,
)
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
    discover_prefect_server_url,
)
from pirlo.infrastructure.repository import JsonFileWorkflowRepository
from pirlo.infrastructure.services.llm_workflow import LlmWorkflowRunner
from pirlo.infrastructure.services.playwright_workflow import PlaywrightReplayRunner
from pirlo.infrastructure.services.self_healing_workflow import SelfHealingRunner
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory


@task(name="Pre-Register Run in pirlo.db")
async def preregister_run_task(
    workspace: Path, playbook: str, task_id: str, run_id: str
) -> Run:
    """Pre-registers run in pirlo.db before execution starts."""
    db_path = workspace / "pirlo.db"
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    repo = SqliteRunHistoryRepository(conn)

    run = Run(
        run_id=run_id,
        task_id=task_id,
        playbook=playbook,
        status=RunStatus.STARTED,
        parameter_file_location=f"{playbook}/runs/{run_id}/params.json",
        log_file_location=f"{playbook}/runs/{run_id}/run.log",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
    )
    repo.save(run)
    conn.close()
    return run


from rich.console import Console
from rich.status import Status

from pirlo.playbooks.autopass.adapters.browser_manager import CloakBrowserManager
from pirlo.playbooks.autopass.adapters.cdp_checker import HttpCdpConnectionChecker
from pirlo.playbooks.autopass.core.ports import ProgressListener
from pirlo.playbooks.autopass.core.use_cases import RunAutopassUseCase


class PrefectProgressListener(ProgressListener):
    """Progress listener for Prefect task execution logs with live Rich spinners."""

    console: Console

    def __init__(self):
        super().__init__()
        self.console = Console(force_terminal=True)

    def status_context(self, message: str) -> Status:
        return self.console.status(
            f"[bold green]🏃 {message}[/bold green]", spinner="dots"
        )

    def show_warning(self, message: Any, detail: str | None = None) -> None:
        self.console.print(f"🟨 [yellow]{message}: {detail or ''}[/yellow]")

    def show_goal(self, message: str, detail: str | None = None) -> None:
        self.console.print(f"⚽ [bold green]{message}: {detail or ''}[/bold green]")

    def show_red_card(self, message: str, detail: str | None = None) -> None:
        self.console.print(f"🟥 [bold red]{message}: {detail or ''}[/bold red]")


@task(name="Self-Healing Autopass Execution Worker")
async def run_self_healing_worker_task(
    task_prompt: str,
    profile_path: Path,
    headless: bool,
    cdp_port: int,
    options: AutopassExecutionOptions,
    run_dir: Path,
    run_name: str | None = None,
    run_id: str | None = None,
) -> str:
    """Directly executes SelfHealingRunner inside a Prefect task."""
    cdp_url = f"http://localhost:{cdp_port}"
    workspace = get_workspace_path()
    runs_dir = workspace / "autopass" / "runs"
    repository = JsonFileWorkflowRepository(directory=runs_dir)
    browser_config = BrowserConfig(cdp_url=cdp_url)

    db_path = workspace / "pirlo.db"
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    history_repo = SqliteRunHistoryRepository(conn)

    transform_llm = LlmFactory.create_langchain_llm(
        link=options.analyst, temperature=0.0, timeout=120.0
    )
    thinking_llm = LlmFactory.create_browser_use_llm(
        link=options.playmaker, temperature=0.0, timeout=120.0
    )

    replay_runner = PlaywrightReplayRunner(
        repository=repository,
        llm=transform_llm,
        browser_config=browser_config,
        run_history_repository=history_repo,
    )

    gif_setting = run_dir / "agent_history.gif" if options.generate_gif else False

    agent_factory = DefaultBrowserAgentFactory(
        llm=thinking_llm,
        use_vision=options.use_vision,
        max_failures=options.max_failures,
        retry_delay=options.retry_delay,
        generate_gif=gif_setting,
    )
    fallback_runner = LlmWorkflowRunner(
        agent_factory=agent_factory,
        repository=repository,
        browser_config=browser_config,
        run_history_repository=history_repo,
    )

    self_healing_runner = SelfHealingRunner(
        replay_runner=replay_runner,
        fallback_runner=fallback_runner,
        repository=repository,
    )

    browser_manager = CloakBrowserManager()
    cdp_checker = HttpCdpConnectionChecker(cdp_url)

    use_case = RunAutopassUseCase(
        browser_manager=browser_manager,
        cdp_checker=cdp_checker,
        workflow_runner=self_healing_runner,
    )

    try:
        return await use_case.run(
            task_prompt=task_prompt,
            profile_path=profile_path,
            headless=headless,
            cdp_port=cdp_port,
            listener=PrefectProgressListener(),
            run_name=run_name,
            run_id=run_id,
        )
    finally:
        conn.close()


@task(name="Finalize Run Status in pirlo.db")
async def finalize_run_task(workspace: Path, run_id: str, status: RunStatus):
    """Updates run status to COMPLETED or FAILED in pirlo.db."""
    db_path = workspace / "pirlo.db"
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    repo = SqliteRunHistoryRepository(conn)
    run = repo.get_by_id(run_id)
    if run:
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)
        repo.save(run)
    conn.close()


@flow(name="Pirlo Generic Flow")
async def pirlo_generic_flow(
    workspace: Path,
    pitch_name: str,
    run_id: str,
    worker_fn: Callable[[], Any],
    task_id: str | None = None,
) -> Any:
    if not task_id:
        task_id = generate_task_id(pitch_name, {"run_id": run_id})

    @task(name=f"Worker: {pitch_name} ({run_id})")
    async def prefect_worker():
        res = worker_fn()
        if inspect.isawaitable(res):
            return await res
        return res

    await preregister_run_task(workspace, pitch_name, task_id, run_id)
    try:
        result = await prefect_worker()
        await finalize_run_task(workspace, run_id, RunStatus.COMPLETED)
        return result
    except Exception:
        await finalize_run_task(workspace, run_id, RunStatus.FAILED)
        raise


class SmartPrefectTaskOrchestrator(TaskOrchestrator):
    """
    Smart Prefect Adapter:
    - Auto-discovers active local Prefect server & occupied ports.
    - Prints live Web UI link if server is active.
    - Seamlessly falls back to Ephemeral Engine Mode if no server is running.
    - Supports recurring schedule deployment via --schedule option.
    """

    name = "prefect"

    server_url = Parameter(
        str,
        default=None,
        help="Prefect Server API endpoint URL (e.g. http://localhost:4200/api)",
        env_name="SERVER_URL",
    )
    work_pool = Parameter(
        str,
        default=None,
        help="Prefect work pool name for scheduled deployments",
        env_name="WORK_POOL",
    )

    def __init__(self, server_url: str | None = None, work_pool: str | None = None):
        self.server_url = server_url
        self.work_pool = work_pool

    async def execute(
        self,
        pitch: Pitch,
        worker_fn: Callable[[], Any],
    ) -> Any:
        workspace = get_workspace_path()
        pitch_name = (
            pitch._resolve_playbook_name()
            if hasattr(pitch, "_resolve_playbook_name")
            else getattr(pitch, "name", "autopass")
        )

        from pirlo.core.services.schedule_resolver import ScheduleResolver

        run_dir = getattr(pitch, "run_dir", None) or (
            workspace / pitch_name / "runs" / pitch.run_id
        )
        run_id = pitch.run_id
        cron_schedule = ScheduleResolver.resolve(getattr(pitch, "schedule", None))

        def get_active_task_prefix() -> str:
            with contextlib.suppress(Exception):
                from prefect.context import get_run_context

                ctx = get_run_context()
                if hasattr(ctx, "task_run") and ctx.task_run:
                    task_name = getattr(ctx.task_run, "name", None) or getattr(
                        ctx.task_run, "task_key", "Task"
                    )
                    return f"[{task_name}]"
                if hasattr(ctx, "flow_run") and ctx.flow_run:
                    return f"[{ctx.flow_run.name}]"
            return f"[{pitch_name.capitalize()} Flow]"

        from prefect.settings import (
            PREFECT_API_URL,
            PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
            temporary_settings,
        )

        from pirlo.infrastructure.services.log_streamer import capture_run_logs

        with capture_run_logs(run_dir, get_prefix_fn=get_active_task_prefix):
            # 1. Discover or resolve active Prefect server URL
            active_api_url = self.server_url or discover_prefect_server_url()

            if cron_schedule:
                if not active_api_url:
                    raise RuntimeError(
                        "⚠️ Prefect Server is required for --schedule. "
                        "Please start a local server with 'prefect server start' or configure PREFECT_API_URL."
                    )

                from prefect.client.schemas.schedules import CronSchedule

                web_ui_base = active_api_url.rstrip("/").replace("/api", "")
                print(f"⏰ Scheduling Prefect Flow with cron: '{cron_schedule}'")
                print(f"🌐 Prefect Server Detected: {web_ui_base}")

                schedule = CronSchedule(cron=cron_schedule, timezone="UTC")
                deployment = await pirlo_generic_flow.to_deployment(  # type: ignore[misc]
                    name=f"pirlo-scheduled-{run_id}",
                    schedule=schedule,  # type: ignore[arg-type]
                    work_pool_name=self.work_pool,
                )

                print(
                    f"✅ Created scheduled Prefect deployment: pirlo-scheduled-{run_id}"
                )
                return deployment

            override_settings: dict[Any, Any]
            if active_api_url:
                web_ui_base = active_api_url.rstrip("/").replace("/api", "")
                print(f"🌐 Prefect Server Detected: {web_ui_base}")
                override_settings = {PREFECT_API_URL: active_api_url}
            else:
                print("⚡ Running in Prefect Ephemeral Mode (In-Process)")
                override_settings = {
                    PREFECT_API_URL: None,
                    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
                }

            # 2. Execute Prefect flow under temporary settings
            task_id = getattr(pitch, "task_id", None) or getattr(
                pitch, "run_name", None
            )
            with temporary_settings(override_settings):
                result = await pirlo_generic_flow(
                    workspace=workspace,
                    pitch_name=pitch_name,
                    run_id=run_id,
                    worker_fn=worker_fn,
                    task_id=task_id,
                )

        print(
            f"\n💡 To view detailed inspection & execution history, run:\n"
            f"   pirlo run show {run_id}"
        )
        return result
