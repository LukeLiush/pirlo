from __future__ import annotations

from pathlib import Path

from pirlo.core.config import DEFAULT_WORK_POOL
from pirlo.core.models.orchestrator import (
    ROUTINE_PRESETS,
    OrchestratorLink,
    RoutineRegistration,
)
from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
    PrefectLink,
    PrefectRoutineRegistration,
)
from pirlo.infrastructure.adapters.storage.json_orchestrator_repository import (
    JsonOrchestratorRepository,
)


def test_routine_presets() -> None:
    assert ROUTINE_PRESETS["hourly"] == "0 * * * *"
    assert ROUTINE_PRESETS["daily"] == "0 9 * * *"
    assert ROUTINE_PRESETS["weekly"] == "0 9 * * 1"
    assert ROUTINE_PRESETS["monthly"] == "0 9 1 * *"


def test_prefect_link_defaults() -> None:
    link = PrefectLink(name="local")
    assert link.name == "local"
    assert link.engine == "prefect"
    assert link.server_url == "ephemeral"
    assert link.work_pool == DEFAULT_WORK_POOL
    assert link.is_ephemeral is True


def test_prefect_link_to_dict_flat() -> None:
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.company:4200/api",
        work_pool="custom-pool",
    )
    data = link.to_dict()
    assert isinstance(data, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
    assert data["name"] == "prod"
    assert data["engine"] == "prefect"
    assert data["server_url"] == "http://prefect.company:4200/api"
    assert data["work_pool"] == "custom-pool"


def test_prefect_link_from_dict() -> None:
    raw_data = {
        "engine": "prefect",
        "server_url": "http://prefect.company:4200/api",
        "work_pool": "custom-pool",
    }
    link = OrchestratorLink.from_dict("prod", raw_data)
    assert isinstance(link, PrefectLink)
    assert link.name == "prod"
    assert link.engine == "prefect"
    assert link.server_url == "http://prefect.company:4200/api"
    assert link.work_pool == "custom-pool"
    assert link.is_ephemeral is False


def test_prefect_routine_registration() -> None:
    reg = PrefectRoutineRegistration(
        registration_id="dep-12345",
        play_name="daily_scraper",
        routine="0 9 * * *",
        dashboard_url="http://prefect:4200/deployments/dep-12345",
        work_pool="custom-pool",
    )
    assert isinstance(reg, RoutineRegistration)
    assert reg.registration_id == "dep-12345"
    assert reg.play_name == "daily_scraper"
    assert reg.routine == "0 9 * * *"
    assert reg.orchestrator == "prefect"
    assert reg.dashboard_url == "http://prefect:4200/deployments/dep-12345"
    assert reg.work_pool == "custom-pool"


def test_json_orchestrator_repository(tmp_path: Path) -> None:
    repo_file = tmp_path / "orchestrators.json"
    repo = JsonOrchestratorRepository(repo_file)

    # 1. Initially empty
    assert repo.list_all() == []
    assert repo.get_by_name("prod") is None

    # 2. Save a link
    prod_link = PrefectLink(
        name="prod",
        server_url="http://prefect:4200/api",
        work_pool="prod-pool",
    )
    repo.save(prod_link)

    # 3. Retrieve
    retrieved = repo.get_by_name("prod")
    assert retrieved is not None
    assert isinstance(retrieved, PrefectLink)
    assert retrieved.name == "prod"
    assert retrieved.server_url == "http://prefect:4200/api"
    assert retrieved.work_pool == "prod-pool"

    # 4. List all
    all_links = repo.list_all()
    assert len(all_links) == 1
    assert all_links[0].name == "prod"

    # 5. Delete
    assert repo.delete("prod") is True
    assert repo.get_by_name("prod") is None
    assert repo.list_all() == []
    assert repo.delete("nonexistent") is False
