from pathlib import Path

from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.storage.composite_link_repository import (
    CompositeLinkRepository,
)


def test_composite_link_repository_overlay_precedence(tmp_path: Path):
    connect_path = tmp_path / "connect" / "links.json"
    static_path = tmp_path / "links.json"

    repo = CompositeLinkRepository(connect_path=connect_path, static_path=static_path)

    # 1. Save static link
    static_link = LlmLink(
        name="serve-ollama",
        provider="ollama",
        model="qwen2.5",
        api_key="static-key",
        base_url="http://localhost:11434/v1",
        source="static",
    )
    repo.save(static_link)

    # 2. Get static link
    fetched = repo.get_by_name("serve-ollama")
    assert fetched is not None
    assert fetched.model == "qwen2.5"
    assert fetched.source == "static"

    # 3. Add dynamic connect link overlay with same name
    connect_repo = repo.connect_repo
    connect_link = LlmLink(
        name="serve-ollama",
        provider="ollama",
        model="qwen3.2",
        api_key="ollama",
        base_url="http://127.0.0.1:11435/v1",
        source="pirlo-connect",
    )
    connect_repo.save(connect_link)

    # 4. Get link should return dynamic connect overlay
    fetched_overlay = repo.get_by_name("serve-ollama")
    assert fetched_overlay is not None
    assert fetched_overlay.model == "qwen3.2"
    assert fetched_overlay.source == "pirlo-connect"
    assert fetched_overlay.base_url == "http://127.0.0.1:11435/v1"

    # 5. List all merges overlay
    all_links = repo.list_all()
    assert len(all_links) == 1
    assert all_links[0].source == "pirlo-connect"

    # 6. Deleting connect link restores static link visibility
    connect_repo.delete("serve-ollama")
    reverted = repo.get_by_name("serve-ollama")
    assert reverted is not None
    assert reverted.source == "static"
    assert reverted.model == "qwen2.5"
