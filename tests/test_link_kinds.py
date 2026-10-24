# tests/test_link_kinds.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pirlo.core.models.link import LlmLink, MissingModelError, link_from_dict
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)
from pirlo.infrastructure.services.llm_client import LlmClient

LEGACY_ENTRY = {
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "api_key": "key123",
    "base_url": "https://gemini.example",
    "source": "pirlo-connect",
    "is_default": True,
}


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=4))


def test_entry_without_kind_loads_as_api_link():
    link = link_from_dict("g", LEGACY_ENTRY)

    assert isinstance(link, LlmLink)
    assert link.kind == "api"
    assert link.default_model == "gemini-2.5-flash"
    assert link.is_default is True


def test_unknown_kind_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    path = tmp_path / "links.json"
    _write(path, {"g": LEGACY_ENTRY, "future": {"kind": "teleport", "x": 1}})
    repo = JsonLinkRepository(path)

    with caplog.at_level(logging.WARNING, logger="pirlo.core.models.link"):
        names = [link.name for link in repo.list_all()]

    assert names == ["g"]
    assert repo.get_by_name("future") is None
    assert "unknown kind 'teleport'" in caplog.text


def test_resaving_a_legacy_entry_only_adds_the_kind(tmp_path: Path):
    path = tmp_path / "links.json"
    _write(path, {"g": LEGACY_ENTRY})
    repo = JsonLinkRepository(path)

    link = repo.get_by_name("g")
    assert link is not None
    repo.save(link)

    assert json.loads(path.read_text()) == {"g": {"kind": "api", **LEGACY_ENTRY}}


def test_explicit_model_beats_the_link_default():
    link = LlmLink(name="g", provider="gemini", api_key="k", default_model="flash")

    assert link.resolve_model("pro") == "pro"
    assert link.resolve_model(None) == "flash"


def test_missing_model_raises_with_guidance():
    link = LlmLink(name="g", provider="gemini", api_key="k")

    with pytest.raises(MissingModelError, match="pass --model"):
        link.resolve_model(None)


def test_link_without_default_model_omits_the_model_key():
    data = LlmLink(name="g", provider="gemini", api_key="k").to_dict()

    assert "model" not in data
    assert link_from_dict("g", data).default_model is None  # type: ignore[union-attr]


def test_llm_client_uses_explicit_model_and_never_calls_without_one():
    link = LlmLink(name="g", provider="gemini", api_key="k", default_model="flash")
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"))]

    with patch("litellm.completion", return_value=response) as completion:
        LlmClient.completion(link=link, prompt="hi", model="pro")
        assert completion.call_args.kwargs["model"] == "pro"

        bare = LlmLink(name="b", provider="gemini", api_key="k")
        with pytest.raises(MissingModelError):
            LlmClient.completion(link=bare, prompt="hi")
        assert completion.call_count == 1
