# tests/conftest.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_test_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
):
    """Isolates Prefect result storage and profiles from the host and from other tests."""
    storage_path = tmp_path_factory.mktemp("prefect_test_storage")
    monkeypatch.setenv("PREFECT_LOCAL_STORAGE_PATH", str(storage_path))
    # Keep a developer's `prefect config set` from steering server discovery.
    profiles_path = tmp_path_factory.mktemp("prefect_profiles") / "profiles.toml"
    monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))
