# tests/test_link_commands.py
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pirlo.core.models.link import SUPPORTED_PROVIDERS, LlmLink
from pirlo.infrastructure.adapters.cli.link_commands import (
    run_create,
    run_delete,
    run_test,
)
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)


@pytest.fixture
def repo(tmp_path: Path) -> JsonLinkRepository:
    return JsonLinkRepository(tmp_path / "links.json")


def test_delete_existing_link_succeeds(
    repo: JsonLinkRepository, capsys: pytest.CaptureFixture[str]
):
    repo.save(LlmLink(name="g", provider="gemini", default_model="m", api_key="k"))

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


def test_create_without_model_saves_a_link_with_no_default(repo: JsonLinkRepository):
    args = argparse.Namespace(
        name="o",
        provider="openai",
        model=None,
        api_key="sk-x",
        base_url=None,
        test=True,
    )

    with patch("litellm.completion") as completion:
        run_create(repo, args, SUPPORTED_PROVIDERS)

    saved = repo.get_by_name("o")
    assert isinstance(saved, LlmLink)
    assert saved.default_model is None
    completion.assert_not_called()  # --test is skipped, not attempted, without a model


def test_link_test_without_any_model_fails_without_a_request(
    repo: JsonLinkRepository, capsys: pytest.CaptureFixture[str]
):
    repo.save(LlmLink(name="o", provider="openai", api_key="sk-x"))

    with patch("litellm.completion") as completion, pytest.raises(SystemExit) as exc:
        run_test(repo, "o")

    assert exc.value.code == 1
    assert "pass --model" in capsys.readouterr().out
    completion.assert_not_called()


def test_link_test_uses_the_model_flag(repo: JsonLinkRepository):
    repo.save(LlmLink(name="o", provider="openai", api_key="sk-x"))
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="OK"))]

    with patch("litellm.completion", return_value=response) as completion:
        run_test(repo, "o", model="gpt-x")

    assert completion.call_args.kwargs["model"] == "gpt-x"
