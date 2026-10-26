from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.infrastructure.adapters.orchestrator.prefect.models import PrefectLink
from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
    Execution,
    PrefectTarget,
)


def test_ephemeral_link_targets_no_server():
    target = PrefectTarget.from_link(PrefectLink())

    assert target.execution is Execution.EPHEMERAL
    assert target.server.api_url is None


def test_ephemeral_link_keeps_its_pool_and_storage_for_routines():
    link = PrefectLink(work_pool="nightly", code_storage="in_memory")

    target = PrefectTarget.from_link(link)

    assert target.work_pool == "nightly"
    assert target.code_storage == "in_memory"


def test_server_link_with_pool_submits_to_the_pool():
    target = PrefectTarget.from_link(
        PrefectLink(server_url="http://h:4200", work_pool="prod-pool")
    )

    assert target.execution is Execution.WORK_POOL
    assert target.work_pool == "prod-pool"
    assert target.server.api_url == "http://h:4200/api"


def test_server_link_without_pool_runs_in_process():
    target = PrefectTarget.from_link(
        PrefectLink(server_url="http://h:4200", work_pool="")
    )

    assert target.execution is Execution.IN_PROCESS
    assert target.work_pool == DEFAULT_WORK_POOL
