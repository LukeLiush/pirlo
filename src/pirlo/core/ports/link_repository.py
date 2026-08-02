from abc import ABC, abstractmethod
from typing import Optional
from pirlo.core.models.link import LlmLink


class LinkRepository(ABC):
    @abstractmethod
    def save(self, link: LlmLink) -> None:
        """Saves a link to storage."""
        pass

    @abstractmethod
    def get_by_name(self, name: str) -> Optional[LlmLink]:
        """Retrieves a link by its name."""
        pass

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Deletes a link by its name. Returns True if deleted."""
        pass

    @abstractmethod
    def list_all(self) -> list[LlmLink]:
        """Lists all registered links."""
        pass
