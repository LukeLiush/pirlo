# pirlo/infrastructure/adapters/orchestrator/prefect_lifecycle.py
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prefect import flow, task

from pirlo.core.models.link import LlmLink
from pirlo.core.models.plan import DecomposerPlan
from pirlo.core.models.run import Run, RunStatus
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.services.llm_client import LlmClient


def _connect(workspace: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        str(workspace / "pirlo.db"), timeout=30.0, check_same_thread=False
    )


@task(name="Pre-Register Run in pirlo.db")
async def preregister_run_task(
    workspace: Path, playbook: str, run_name: str, run_id: str
) -> Run:
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


@task(name="Finalize Run Status in pirlo.db")
async def finalize_run_task(workspace: Path, run_id: str, status: RunStatus) -> None:
    conn = _connect(workspace)
    try:
        repo = SqliteRunHistoryRepository(conn)
        run = repo.get_by_id(run_id)
        if run:
            run.status = status
            run.finished_at = datetime.now(UTC)
            run.updated_at = datetime.now(UTC)
            repo.save(run)
    finally:
        conn.close()


@task(name="Aggregate Subtask Results")
async def aggregate_subtask_results_task(
    original_prompt: str,
    aggregation_instruction: str,
    subtask_results: list[dict[str, Any]],
    link: LlmLink | None = None,
) -> str:
    prompt = (
        f"Original User Request: {original_prompt}\n\n"
        f"Aggregation Instructions: {aggregation_instruction}\n\n"
        f"Subtask Results Data: {json.dumps(subtask_results, indent=2)}\n\n"
        f"Please combine and summarize these results according to the aggregation instructions."
    )
    if link:
        return await LlmClient.acompletion(
            link=link,
            prompt=prompt,
            temperature=0.0,
            timeout=120.0,
        )

    return f"Aggregator unable to process prompt: {prompt}"


@flow(name="Pirlo Decomposed Multi-Target Flow")
async def pirlo_decomposed_flow(
    plan: DecomposerPlan,
    worker_fn: Callable[..., Awaitable[Any]] | Callable[..., Any],
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
    if workspace and playbook and run_id:
        await preregister_run_task(workspace, playbook, run_name or run_id, run_id)

    try:
        # 1. Dispatch subtasks concurrently
        subtask_futures = [
            worker_fn(task_prompt=subtask.task_prompt, site=subtask.target_site)
            for subtask in plan.subtasks
        ]
        subtask_results = await asyncio.gather(*subtask_futures, return_exceptions=True)

        # 2. Format results for the aggregator
        formatted_results: list[dict[str, Any]] = []
        for subtask, subtask_result in zip(plan.subtasks, subtask_results):
            if isinstance(subtask_result, Exception):
                formatted_results.append(
                    {
                        "site": subtask.target_site,
                        "status": "FAILED",
                        "error": str(subtask_result),
                    }
                )
            else:
                formatted_results.append(
                    {
                        "site": subtask.target_site,
                        "status": "COMPLETED",
                        "data": str(subtask_result),
                    }
                )

        # 3. Aggregate
        result: str = await aggregate_subtask_results_task(
            original_prompt=plan.original_prompt,
            aggregation_instruction=plan.aggregation_prompt,
            subtask_results=formatted_results,
            link=link,
        )
        if workspace and playbook and run_id:
            await finalize_run_task(workspace, run_id, RunStatus.COMPLETED)
        return result
    except Exception:
        if workspace and playbook and run_id:
            await finalize_run_task(workspace, run_id, RunStatus.FAILED)
        raise
