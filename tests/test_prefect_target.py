from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
    Execution,
    PrefectTarget,
)


def test_ephemeral_target_has_no_server():
    target = PrefectTarget.ephemeral()

    assert target.execution is Execution.EPHEMERAL
    assert target.server.api_url is None
    assert target.server.web_ui_base is None


def test_ephemeral_target_uses_default_pool_and_storage_for_routines():
    target = PrefectTarget.ephemeral()

    assert target.work_pool == DEFAULT_WORK_POOL
    assert target.code_storage == "prefect_artifact"
