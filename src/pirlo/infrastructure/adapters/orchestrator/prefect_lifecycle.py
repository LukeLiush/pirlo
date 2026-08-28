# pirlo/infrastructure/adapters/orchestrator/prefect_lifecycle.py
from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from prefect import flow, task

from pirlo.core.models.link import LlmLink
from pirlo.core.models.plan import DecomposerPlan
from pirlo.core.models.run import Run, RunStatus
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.services.llm_client import LlmClient

logger = logging.getLogger(__name__)


class SubtaskCompleted(TypedDict):
    site: str
    status: Literal["COMPLETED"]
    data: str


class SubtaskFailed(TypedDict):
    site: str
    status: Literal["FAILED"]
    error: str


SubtaskResult = SubtaskCompleted | SubtaskFailed


def _connect(workspace: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        str(workspace / "pirlo.db"), timeout=30.0, check_same_thread=False
    )


def _render_results(results: Sequence[SubtaskResult]) -> str:
    """Renders subtask results as readable text rather than escaped JSON."""
    blocks: list[str] = []
    for result in results:
        header = f"### {result['site']} ({result['status']})"
        body = (
            result["data"]
            if result["status"] == "COMPLETED"
            else f"Error: {result['error']}"
        )
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


@task(name="Pre-Register Run in pirlo.db")
async def preregister_run_task(
    workspace: Path, playbook: str, run_name: str, run_id: str
) -> Run:
    def _save() -> Run:
        conn = _connect(workspace)
        try:
            repo = SqliteRunHistoryRepository(conn)
            now = datetime.now(UTC)
            run = Run(
                run_id=run_id,
                run_name=run_name,
                playbook=playbook,
                status=RunStatus.STARTED,
                parameter_file_location=f"{playbook}/runs/{run_id}/params.json",
                log_file_location=f"{playbook}/runs/{run_id}/run.log",
                created_at=now,
                updated_at=now,
                started_at=now,
            )
            repo.save(run)
            return run
        finally:
            conn.close()

    return await asyncio.to_thread(_save)


@task(name="Finalize Run Status in pirlo.db")
async def finalize_run_task(workspace: Path, run_id: str, status: RunStatus) -> None:
    def _update() -> None:
        conn = _connect(workspace)
        try:
            repo = SqliteRunHistoryRepository(conn)
            run = repo.get_by_id(run_id)
            if run is None:
                logger.warning("Cannot finalize unknown run_id %s", run_id)
                return
            now = datetime.now(UTC)
            run.status = status
            run.finished_at = now
            run.updated_at = now
            repo.save(run)
        finally:
            conn.close()

    await asyncio.to_thread(_update)


@task(name="Aggregate Subtask Results")
async def aggregate_subtask_results_task(
    original_prompt: str,
    aggregation_instruction: str,
    subtask_results: Sequence[SubtaskResult],
    link: LlmLink | None = None,
) -> str:
    prompt = (
        f"Original User Request: {original_prompt}\n\n"
        f"Aggregation Instructions: {aggregation_instruction}\n\n"
        f"Subtask Results:\n\n{_render_results(subtask_results)}\n\n"
        f"Please combine and summarize these results according to the "
        f"aggregation instructions."
    )
    if link is None:
        return f"Aggregator unable to process prompt: {prompt}"

    return await LlmClient.acompletion(
        link=link,
        prompt=prompt,
        temperature=0.0,
        timeout=120.0,
    )


@flow(name="Pirlo Decomposed Multi-Target Flow")
async def pirlo_decomposed_flow(
    plan: DecomposerPlan,
    worker_fn: Callable[..., Awaitable[Any]],
    link: LlmLink | None = None,
    workspace: Path | None = None,
    playbook: str | None = None,
    run_name: str | None = None,
    run_id: str | None = None,
) -> str:
    """Dispatches all subtasks concurrently, then merges results via the aggregator.

    Prefect settings (server vs. ephemeral) are applied by the caller
    (the orchestrator) before this flow runs, so it does not manage them here.
    """
    tracked = workspace is not None and playbook is not None and run_id is not None

    if tracked:
        assert workspace and playbook and run_id  # narrowing for the type checker
        await preregister_run_task(workspace, playbook, run_name or run_id, run_id)

    async def _finalize(status: RunStatus) -> None:
        if not tracked:
            return
        assert workspace and run_id
        try:
            await finalize_run_task(workspace, run_id, status)
        except Exception:
            logger.exception("Failed to finalize run %s as %s", run_id, status)

    try:
        subtask_results = await asyncio.gather(
            *(
                worker_fn(task_prompt=subtask.task_prompt, site=subtask.target_site)
                for subtask in plan.subtasks
            ),
            return_exceptions=True,
        )

        formatted_results: list[SubtaskResult] = []
        for subtask, subtask_result in zip(plan.subtasks, subtask_results, strict=True):
            if isinstance(subtask_result, BaseException):
                logger.warning(
                    "Subtask for %s failed: %r", subtask.target_site, subtask_result
                )
                formatted_results.append(
                    SubtaskFailed(
                        site=subtask.target_site,
                        status="FAILED",
                        error=f"{type(subtask_result).__name__}: {subtask_result}",
                    )
                )
            else:
                formatted_results.append(
                    SubtaskCompleted(
                        site=subtask.target_site,
                        status="COMPLETED",
                        data=str(subtask_result),
                    )
                )

        result: str = await aggregate_subtask_results_task(
            original_prompt=plan.original_prompt,
            aggregation_instruction=plan.aggregation_prompt,
            subtask_results=formatted_results,
            link=link,
        )
    except Exception:
        await _finalize(RunStatus.FAILED)
        raise
    else:
        await _finalize(RunStatus.COMPLETED)
        return result
