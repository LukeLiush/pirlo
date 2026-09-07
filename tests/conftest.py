# tests/conftest.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_test_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
):
    """Isolates Prefect result storage per test run to prevent cross-test and host cache pollution."""
    storage_path = tmp_path_factory.mktemp("prefect_test_storage")
    monkeypatch.setenv("PREFECT_LOCAL_STORAGE_PATH", str(storage_path))
