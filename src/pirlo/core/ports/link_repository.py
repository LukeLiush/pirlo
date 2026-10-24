from abc import ABC, abstractmethod

from pirlo.core.models.link import Link


class LinkRepository(ABC):
    @abstractmethod
    def save(self, link: Link) -> None:
        """Saves a link to storage."""

    @abstractmethod
    def get_by_name(self, name: str) -> Link | None:
        """Retrieves a link by its name."""

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Deletes a link by its name. Returns True if deleted."""

    @abstractmethod
    def list_all(self) -> list[Link]:
        """Lists all registered links."""

    def get_default_link(self) -> Link | None:
        """Retrieves active link marked as default."""
        return next((link for link in self.list_all() if link.is_default), None)
