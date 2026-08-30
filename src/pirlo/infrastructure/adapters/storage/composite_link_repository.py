from pathlib import Path

from pirlo.core.config import get_workspace_path
from pirlo.core.models.link import LlmLink
from pirlo.core.ports.link_repository import LinkRepository
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)


class CompositeLinkRepository(LinkRepository):
    """Layered Link Repository combining dynamic connect links overlay with user static links."""

    def __init__(
        self,
        connect_path: Path | None = None,
        static_path: Path | None = None,
    ) -> None:
        workspace_path = get_workspace_path()
        if connect_path is None:
            connect_path = workspace_path / "connect" / "links.json"
        if static_path is None:
            static_path = workspace_path / "links.json"

        self.connect_repo = JsonLinkRepository(connect_path)
        self.static_repo = JsonLinkRepository(static_path)

    def save(self, link: LlmLink) -> None:
        """Saves user link to static repository."""
        self.static_repo.save(link)

    def get_by_name(self, name: str) -> LlmLink | None:
        """Looks up link in connect dynamic overlay first, falling back to static user links."""
        link = self.connect_repo.get_by_name(name)
        if link is not None:
            return link
        return self.static_repo.get_by_name(name)

    def delete(self, name: str) -> bool:
        """Deletes link from both repositories if present."""
        connect_deleted = self.connect_repo.delete(name)
        static_deleted = self.static_repo.delete(name)
        return connect_deleted or static_deleted

    def list_all(self) -> list[LlmLink]:
        """Lists active links, merging connect overlay with static links."""
        connect_links = self.connect_repo.list_all()
        connect_names = {link.name for link in connect_links}

        static_links = [
            link
            for link in self.static_repo.list_all()
            if link.name not in connect_names
        ]
        return connect_links + static_links
