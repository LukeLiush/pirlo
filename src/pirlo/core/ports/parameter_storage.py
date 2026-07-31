from abc import ABC, abstractmethod
from typing import Any


class ParameterStorage(ABC):
    """Abstract port for storing and loading playbook run parameters."""

    @abstractmethod
    def save_parameters(self, location: str, parameters: dict[str, Any]) -> None:
        """Saves parameter configuration dict to the specified relative location."""

    @abstractmethod
    def load_parameters(self, location: str) -> dict[str, Any]:
        """Loads parameter configuration dict from the specified relative location."""
