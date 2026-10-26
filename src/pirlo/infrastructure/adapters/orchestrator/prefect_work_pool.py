from prefect.settings import PREFECT_API_URL, temporary_settings

from pirlo.core.config import DEFAULT_WORK_POOL


def ensure_work_pool(api_url: str, name: str = DEFAULT_WORK_POOL) -> bool:
    """Creates a process-type work pool on the server if it is missing.

    Returns True when the pool was created, False when it already existed.
    """
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import WorkPoolCreate
    from prefect.exceptions import ObjectNotFound

    with (
        temporary_settings({PREFECT_API_URL: api_url}),
        get_client(sync_client=True) as client,
    ):
        try:
            client.read_work_pool(name)
            return False
        except ObjectNotFound:
            client.create_work_pool(WorkPoolCreate(name=name, type="process"))
            return True


def count_late_runs(api_url: str, name: str = DEFAULT_WORK_POOL) -> int:
    """Counts flow runs in the work pool that are already past their start time."""
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.filters import (
        FlowRunFilter,
        FlowRunFilterState,
        FlowRunFilterStateName,
        WorkPoolFilter,
        WorkPoolFilterName,
    )

    late = FlowRunFilter(
        state=FlowRunFilterState(name=FlowRunFilterStateName(any_=["Late"]))
    )
    in_pool = WorkPoolFilter(name=WorkPoolFilterName(any_=[name]))
    with (
        temporary_settings({PREFECT_API_URL: api_url}),
        get_client(sync_client=True) as client,
    ):
        return client.count_flow_runs(flow_run_filter=late, work_pool_filter=in_pool)
