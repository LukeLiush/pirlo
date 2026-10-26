from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.infrastructure.adapters.orchestrator.prefect.models import PrefectLink
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
    def from_link(cls, link: PrefectLink) -> PrefectTarget:
        if link.is_ephemeral:
            server = PrefectServerSettings(api_url=None)
            execution = Execution.EPHEMERAL
        else:
            server = PrefectServerSettings.resolve(link.server_url)
            execution = Execution.WORK_POOL if link.work_pool else Execution.IN_PROCESS
        return cls(
            server=server,
            execution=execution,
            work_pool=link.work_pool or DEFAULT_WORK_POOL,
            code_storage=link.code_storage,
        )
