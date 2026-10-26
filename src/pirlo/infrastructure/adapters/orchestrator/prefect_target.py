from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pirlo.core.config import DEFAULT_WORK_POOL, is_server_disabled
from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
    PrefectServerSettings,
)


class Execution(StrEnum):
    EPHEMERAL = "ephemeral"  # no server: Prefect's temporary in-process API
    IN_PROCESS = "in_process"  # run in this process, report to a server
    WORK_POOL = "work_pool"  # submit to a work pool; a worker runs it


@dataclass(frozen=True)
class PrefectTarget:
    """Where a run's state goes and where its code executes, decided once."""

    server: PrefectServerSettings
    execution: Execution
    work_pool: str = DEFAULT_WORK_POOL
    code_storage: Literal["in_memory", "prefect_artifact"] = "prefect_artifact"

    @classmethod
    def ephemeral(cls) -> PrefectTarget:
        return cls(PrefectServerSettings(api_url=None), Execution.EPHEMERAL)


def resolve_default_target() -> PrefectTarget:
    """Runs report to a configured Prefect server when one answers, else stay ephemeral."""
    if is_server_disabled():
        return PrefectTarget.ephemeral()
    server = PrefectServerSettings.resolve(None)
    if server.api_url is None:
        return PrefectTarget.ephemeral()
    return PrefectTarget(server, Execution.IN_PROCESS)
