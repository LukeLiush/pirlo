from abc import ABC, abstractmethod

from browser_use import Agent, Browser


class BrowserAgentFactory(ABC):
    @abstractmethod
    def create_agent(self, task: str, browser: Browser) -> Agent:
        """Create a new, stateful Agent instance for the given task."""

    @abstractmethod
    def get_llm_metadata(self) -> tuple[str, str]:
        """Returns (provider_name, model_name) for telemetry/metadata logging."""
