# tests/test_link_commands.py
from __future__ import annotations

from pathlib import Path

import pytest

from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.cli.link_commands import run_delete
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)


@pytest.fixture
def repo(tmp_path: Path) -> JsonLinkRepository:
    return JsonLinkRepository(tmp_path / "links.json")


def test_delete_existing_link_succeeds(
    repo: JsonLinkRepository, capsys: pytest.CaptureFixture[str]
):
    repo.save(LlmLink(name="g", provider="gemini", model="m", api_key="k"))

    run_delete(repo, "g")

    assert repo.get_by_name("g") is None
    assert capsys.readouterr().out == "Successfully deleted link 'g'.\n"


def test_delete_missing_link_exits_with_error(
    repo: JsonLinkRepository, capsys: pytest.CaptureFixture[str]
):
    with pytest.raises(SystemExit) as exc_info:
        run_delete(repo, "nope")

    assert exc_info.value.code == 1
    assert "not found" in capsys.readouterr().out
