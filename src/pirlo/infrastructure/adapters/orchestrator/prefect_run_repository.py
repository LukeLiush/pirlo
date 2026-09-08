# src/pirlo/infrastructure/adapters/orchestrator/prefect_run_repository.py
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from prefect.client.orchestration import PrefectClient, get_client
from prefect.client.schemas.filters import (
    FlowFilter,
    FlowFilterName,
    FlowRunFilter,
    FlowRunFilterName,
    FlowRunFilterTags,
    LogFilter,
    LogFilterFlowRunId,
    LogFilterTaskRunId,
    LogFilterTimestamp,
    TaskRunFilter,
    TaskRunFilterFlowRunId,
)
from prefect.client.schemas.objects import Flow, FlowRun, Log, TaskRun
from prefect.client.schemas.sorting import FlowRunSort, LogSort
from prefect.settings import temporary_settings

from pirlo.core.config import get_workspace_path
from pirlo.core.models.run import PlayRunDetail, Run, RunStatus
from pirlo.core.repository.run_history_repository import RunRepository
from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
    PrefectServerSettings,
)

logger: logging.Logger = logging.getLogger(__name__)


def _map_prefect_state(state_name: str | None) -> RunStatus:
    if not state_name:
        return RunStatus.NOT_STARTED
    s: str = state_name.lower()
    if "complete" in s:
        return RunStatus.COMPLETED
    if "fail" in s or "crash" in s:
        return RunStatus.FAILED
    if "cancel" in s:
        return RunStatus.CANCELLED
    if "skip" in s:
        return RunStatus.SKIPPED
    if "run" in s:
        return RunStatus.RUNNING
    return RunStatus.STARTED


def _extract_run_id(fr: FlowRun) -> str:
    if fr.tags:
        for tag in fr.tags:
            if tag.startswith("pirlo_id:"):
                return tag.split(":", 1)[1]
    return fr.name


class PrefectRunRepository(RunRepository):
    """Queries flow runs, task runs, and logs via Prefect API with local file bookkeeping."""

    def __init__(self, server_url: str | None = None) -> None:
        self._settings: PrefectServerSettings = PrefectServerSettings.resolve(
            server_url
        )
        self._workspace: Path = get_workspace_path()

    def _get_local_play_log_path(
        self, playbook: str, run_id: str, play_id: str
    ) -> Path:
        run_dummy: Run = Run(
            run_id=run_id,
            playbook=playbook,
            status=RunStatus.STARTED,
        )
        return run_dummy.get_play_log_path(self._workspace, play_id)

    async def list_runs(
        self,
        playbook: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[Run]:
        with temporary_settings(self._settings.overrides):
            client: PrefectClient
            async with get_client() as client:
                flow_filter: FlowFilter | None = (
                    FlowFilter(name=FlowFilterName(any_=[playbook]))
                    if playbook
                    else None
                )
                flow_runs: list[FlowRun] = await client.read_flow_runs(
                    sort=FlowRunSort.START_TIME_DESC,
                    limit=limit,
                    flow_filter=flow_filter,
                )

                flow_ids: set[uuid.UUID] = {fr.flow_id for fr in flow_runs}
                flow_map: dict[uuid.UUID, str] = {}
                for fid in flow_ids:
                    f: Flow = await client.read_flow(fid)
                    flow_map[fid] = f.name

                runs: list[Run] = []
                fr: FlowRun
                for fr in flow_runs:
                    st: RunStatus = _map_prefect_state(fr.state_name)
                    if status and st.value.lower() != status.lower():
                        continue

                    duration_sec: float | None = (
                        fr.total_run_time.total_seconds()
                        if fr.total_run_time
                        else (
                            (fr.end_time - fr.start_time).total_seconds()
                            if (fr.start_time and fr.end_time)
                            else None
                        )
                    )
                    pb_name: str = flow_map.get(fr.flow_id, "unknown")
                    dash_url: str | None = (
                        f"{self._settings.web_ui_base}/flow-runs/flow-run/{fr.id}"
                        if self._settings.web_ui_base
                        else None
                    )

                    runs.append(
                        Run(
                            run_id=_extract_run_id(fr),
                            playbook=pb_name,
                            status=st,
                            duration=duration_sec,
                            parameters=fr.parameters or {},
                            started_at=fr.start_time,
                            finished_at=fr.end_time,
                            dashboard_url=dash_url,
                        )
                    )
                return runs

    async def get_by_id(self, run_id: str) -> Run | None:
        with temporary_settings(self._settings.overrides):
            client: PrefectClient
            async with get_client() as client:
                # Query by flow_run_name or by tag pirlo_id:<run_id>
                flow_runs: list[FlowRun] = await client.read_flow_runs(
                    flow_run_filter=FlowRunFilter(
                        name=FlowRunFilterName(any_=[run_id])
                    ),
                    limit=1,
                )
                if not flow_runs:
                    flow_runs = await client.read_flow_runs(
                        flow_run_filter=FlowRunFilter(
                            tags=FlowRunFilterTags(all_=[f"pirlo_id:{run_id}"])
                        ),
                        limit=1,
                    )
                if not flow_runs:
                    return None

                fr: FlowRun = flow_runs[0]
                flow: Flow = await client.read_flow(fr.flow_id)
                st: RunStatus = _map_prefect_state(fr.state_name)
                duration_sec: float | None = (
                    fr.total_run_time.total_seconds()
                    if fr.total_run_time
                    else (
                        (fr.end_time - fr.start_time).total_seconds()
                        if (fr.start_time and fr.end_time)
                        else None
                    )
                )
                dash_url: str | None = (
                    f"{self._settings.web_ui_base}/flow-runs/flow-run/{fr.id}"
                    if self._settings.web_ui_base
                    else None
                )

                error_msg: str | None = None
                if fr.state and fr.state.is_failed():
                    error_msg = fr.state.message

                # Fetch task runs for this flow run
                prefect_tasks: list[TaskRun] = await client.read_task_runs(
                    task_run_filter=TaskRunFilter(
                        flow_run_id=TaskRunFilterFlowRunId(any_=[fr.id])
                    )
                )
                prefect_tasks.sort(
                    key=lambda t: (
                        t.start_time.timestamp()
                        if t.start_time
                        else (t.created.timestamp() if t.created else 0.0)
                    )
                )

                play_runs: list[PlayRunDetail] = []
                tr: TaskRun
                for tr in prefect_tasks:
                    t_st: RunStatus = _map_prefect_state(tr.state_name)
                    t_dur: float | None = (
                        tr.total_run_time.total_seconds()
                        if tr.total_run_time
                        else (
                            (tr.end_time - tr.start_time).total_seconds()
                            if (tr.start_time and tr.end_time)
                            else None
                        )
                    )
                    t_err: str | None = (
                        tr.state.message
                        if (tr.state and tr.state.is_failed())
                        else None
                    )
                    raw_name: str = tr.name
                    play_id: str = raw_name
                    play_name: str = (
                        play_id.split("#", 1)[0] if "#" in play_id else play_id
                    )

                    play_runs.append(
                        PlayRunDetail(
                            play_run_id=str(tr.id),
                            play_name=play_name,
                            play_id=play_id,
                            status=t_st,
                            duration=t_dur,
                            started_at=tr.start_time,
                            finished_at=tr.end_time,
                            error_message=t_err,
                        )
                    )

                return Run(
                    run_id=_extract_run_id(fr),
                    playbook=flow.name,
                    status=st,
                    duration=duration_sec,
                    parameters=fr.parameters or {},
                    started_at=fr.start_time,
                    finished_at=fr.end_time,
                    error_message=error_msg,
                    dashboard_url=dash_url,
                    play_runs=play_runs,
                )

    async def stream_play_logs(
        self,
        run_id: str,
        play_id: str | None = None,
        tail_lines: int = 50,
        follow: bool = False,
    ) -> AsyncIterator[str]:
        run: Run | None = await self.get_by_id(run_id)
        if not run:
            yield f"Error: Run '{run_id}' not found."
            return

        target_play: PlayRunDetail | None = None
        if play_id:
            matches: list[PlayRunDetail] = [
                p for p in run.play_runs if p.play_id == play_id
            ]
            if not matches:
                name_matches: list[PlayRunDetail] = [
                    p for p in run.play_runs if p.play_name == play_id
                ]
                if len(name_matches) == 1:
                    target_play = name_matches[0]
                elif len(name_matches) > 1:
                    yield f"Multiple play instances found for '{play_id}':"
                    for m in name_matches:
                        yield f"  • {m.play_id} (status: {m.status.value})"
                    yield f"\nPlease specify: pirlo run log {run_id}/{name_matches[0].play_id}"
                    return
                else:
                    yield f"Error: Play '{play_id}' not found in run '{run_id}'."
                    return
            else:
                target_play = matches[0]
        else:
            failed_plays: list[PlayRunDetail] = [
                p for p in run.play_runs if p.status == RunStatus.FAILED
            ]
            if failed_plays:
                target_play = failed_plays[0]
                yield f"[Auto-selected failed play: {target_play.play_id}]\n"
            elif len(run.play_runs) == 1:
                target_play = run.play_runs[0]
            elif len(run.play_runs) > 1:
                yield f"Run '{run_id}' contains multiple plays. Please specify one:"
                for p in run.play_runs:
                    yield f"  • {run_id}/{p.play_id} (status: {p.status.value})"
                return

        local_log_file: Path | None = (
            self._get_local_play_log_path(run.playbook, run.run_id, target_play.play_id)
            if target_play
            else None
        )
        if local_log_file:
            local_log_file.parent.mkdir(parents=True, exist_ok=True)

        last_saved_ts: datetime | None = None
        seen_ids_at_last_ts: set[str] = set()

        if local_log_file and local_log_file.exists():
            with open(local_log_file, "r", encoding="utf-8") as f:  # noqa: ASYNC230
                cached_lines: list[str] = [line.rstrip() for line in f]

            for line in cached_lines[-tail_lines:]:
                yield line

            if (
                target_play
                and target_play.status in (RunStatus.COMPLETED, RunStatus.FAILED)
                and not follow
            ):
                return

            meta_cursor_file: Path = local_log_file.with_suffix(".cursor")
            if meta_cursor_file.exists():
                try:
                    last_saved_ts = datetime.fromisoformat(
                        meta_cursor_file.read_text().strip()
                    )
                except (ValueError, OSError):
                    pass

        with temporary_settings(self._settings.overrides):
            client: PrefectClient
            async with get_client() as client:
                flow_runs: list[FlowRun] = await client.read_flow_runs(
                    flow_run_filter=FlowRunFilter(
                        name=FlowRunFilterName(any_=[run_id])
                    ),
                    limit=1,
                )
                if not flow_runs:
                    flow_runs = await client.read_flow_runs(
                        flow_run_filter=FlowRunFilter(
                            tags=FlowRunFilterTags(all_=[f"pirlo_id:{run_id}"])
                        ),
                        limit=1,
                    )
                if not flow_runs:
                    return
                fr_id: uuid.UUID = flow_runs[0].id

                def _append_to_cache(line_str: str, ts: datetime) -> None:
                    if local_log_file:
                        with open(local_log_file, "a", encoding="utf-8") as out:
                            out.write(line_str + "\n")
                        meta_cursor: Path = local_log_file.with_suffix(".cursor")
                        meta_cursor.write_text(ts.isoformat())

                base_filter: LogFilter = (
                    LogFilter(
                        task_run_id=LogFilterTaskRunId(
                            any_=[uuid.UUID(target_play.play_run_id)]
                        ),
                        timestamp=LogFilterTimestamp(after_=cast(Any, last_saved_ts))
                        if last_saved_ts
                        else None,
                    )
                    if target_play
                    else LogFilter(
                        flow_run_id=LogFilterFlowRunId(any_=[fr_id]),
                        timestamp=LogFilterTimestamp(after_=cast(Any, last_saved_ts))
                        if last_saved_ts
                        else None,
                    )
                )

                logs: list[Log] = await client.read_logs(
                    log_filter=base_filter,
                    sort=LogSort.TIMESTAMP_ASC,
                    limit=min(tail_lines, 2000),
                )

                log: Log
                for log in logs:
                    lvl_name: str = logging.getLevelName(log.level)
                    line_formatted: str = f"{log.timestamp.strftime('%H:%M:%S')} [{lvl_name}] {log.message}"
                    yield line_formatted
                    _append_to_cache(line_formatted, log.timestamp)
                    if last_saved_ts != log.timestamp:
                        last_saved_ts = log.timestamp
                        seen_ids_at_last_ts = {str(log.id)}
                    else:
                        seen_ids_at_last_ts.add(str(log.id))

                while follow:
                    current_run: FlowRun = await client.read_flow_run(fr_id)
                    more_filter: LogFilter = (
                        LogFilter(
                            task_run_id=LogFilterTaskRunId(
                                any_=[uuid.UUID(target_play.play_run_id)]
                            )
                            if target_play
                            else None,
                            flow_run_id=LogFilterFlowRunId(any_=[fr_id])
                            if not target_play
                            else None,
                            timestamp=LogFilterTimestamp(
                                after_=cast(Any, last_saved_ts)
                            ),
                        )
                        if last_saved_ts
                        else base_filter
                    )

                    more_logs: list[Log] = await client.read_logs(
                        log_filter=more_filter,
                        sort=LogSort.TIMESTAMP_ASC,
                        limit=200,
                    )
                    for log in more_logs:
                        if str(log.id) not in seen_ids_at_last_ts:
                            lvl_name = logging.getLevelName(log.level)
                            line_formatted = f"{log.timestamp.strftime('%H:%M:%S')} [{lvl_name}] {log.message}"
                            yield line_formatted
                            _append_to_cache(line_formatted, log.timestamp)
                            if last_saved_ts != log.timestamp:
                                last_saved_ts = log.timestamp
                                seen_ids_at_last_ts = {str(log.id)}
                            else:
                                seen_ids_at_last_ts.add(str(log.id))

                    if current_run.state and current_run.state.is_final():
                        break
                    await asyncio.sleep(1.0)
