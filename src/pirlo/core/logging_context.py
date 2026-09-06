# src/pirlo/core/logging_context.py
from __future__ import annotations

import contextlib
import contextvars
import os
import uuid
from collections.abc import Iterator

# Context variables for coroutines and task propagation
_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_run_id", default=None
)
_current_play_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_play_id", default=None
)


def generate_short_run_id(length: int = 8) -> str:
    """Generates an 8-character hex short UUID (e.g. '3a4f8c9b')."""
    return uuid.uuid4().hex[:length]


def get_current_run_id() -> str | None:
    return _current_run_id.get()


def get_current_play_id() -> str | None:
    return _current_play_id.get()


@contextlib.contextmanager
def workflow_logging_context(run_id: str | None) -> Iterator[str]:
    """Sets workflow-level run_id (or generates a short UUID if None)."""
    effective_id = str(run_id) if run_id is not None else generate_short_run_id()
    token_run = _current_run_id.set(effective_id)
    try:
        yield effective_id
    finally:
        _current_run_id.reset(token_run)


@contextlib.contextmanager
def play_logging_context(
    play_id: str,
    run_id: str | None = None,
) -> Iterator[None]:
    """Sets active play_id context (e.g. 'autopass_execute_subtask#1235')."""
    effective_run_id = run_id if run_id is not None else _current_run_id.get()
    token_run = _current_run_id.set(
        str(effective_run_id) if effective_run_id is not None else None
    )
    token_play = _current_play_id.set(play_id)
    try:
        yield
    finally:
        _current_run_id.reset(token_run)
        _current_play_id.reset(token_play)


def resolve_log_prefix() -> tuple[str, int]:
    """Resolves contextual prefix tag and process ID.

    Auto-discovers flow_run_name and task_run_name from Prefect context
    if not explicitly set in contextvars.

    Returns:
        tuple[str, int]: (prefix_tag, pid)
        Example: ('[3a4f8c9b/autopass_execute_subtask#1235 (pid 5678)]', 5678)
                 or ('[3a4f8c9b (pid 5678)]', 5678)
    """
    pid = os.getpid()
    run_id = _current_run_id.get()
    play_id = _current_play_id.get()

    # Fallback to Prefect runtime context auto-discovery
    with contextlib.suppress(Exception):
        from prefect.context import FlowRunContext, TaskRunContext, get_run_context

        ctx = get_run_context()
        if not run_id and isinstance(ctx, (FlowRunContext, TaskRunContext)):
            flow_run = getattr(ctx, "flow_run", None)
            if flow_run and flow_run.name:
                run_id = flow_run.name

        if not play_id and isinstance(ctx, TaskRunContext) and ctx.task_run:
            play_id = ctx.task_run.name or ctx.task_run.task_key

    if run_id and play_id:
        return f"[{run_id}/{play_id} (pid {pid})]", pid
    if run_id:
        return f"[{run_id} (pid {pid})]", pid
    return f"[(pid {pid})]", pid
