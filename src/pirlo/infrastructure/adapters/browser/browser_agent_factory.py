import os
from pathlib import Path
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

from browser_use import Agent, Browser, Controller
from browser_use.agent.prompts import SystemPrompt

from pirlo.core.models.link import LlmLink
from pirlo.core.ports.browser_agent_factory import BrowserAgentFactory
from pirlo.infrastructure.adapters.browser.browser_use_adapters import (
    BrowserUseAdapterRegistry,
)


class DefaultBrowserAgentFactory(BrowserAgentFactory):
    link: LlmLink

    def __init__(
        self,
        link: LlmLink,
        controller: Controller | None = None,
        use_vision: bool = False,
        system_prompt_class: type[SystemPrompt] | None = None,
        include_attributes: list[str] | None = None,
        max_failures: int = 5,
        retry_delay: int = 10,
        generate_gif: bool | str | Path = False,
        max_actions_per_step: int = 10,
        save_conversation_path: str | None = None,
    ):
        """Factory to construct configured browser-use Agent sessions from an LlmLink."""
        self.link = link
        self.controller = controller or Controller()
        self.use_vision = use_vision
        self.system_prompt_class = system_prompt_class
        self.include_attributes = include_attributes
        self.max_failures = max_failures
        self.retry_delay = retry_delay

        if isinstance(generate_gif, Path):
            self.generate_gif: bool | str = str(generate_gif)
        else:
            self.generate_gif = generate_gif

        self.max_actions_per_step = max_actions_per_step
        self.save_conversation_path = save_conversation_path

    def create_agent(
        self,
        task: str,
        browser: Browser | None = None,
        browser_context: Any | None = None,
    ) -> Agent:
        llm = BrowserUseAdapterRegistry.to_chat_model(self.link)
        kwargs: dict[str, Any] = {
            "task": task,
            "llm": llm,
            "controller": self.controller,
            "use_vision": self.use_vision,
            "max_failures": self.max_failures,
            "retry_delay": self.retry_delay,
            "generate_gif": self.generate_gif,
            "max_actions_per_step": self.max_actions_per_step,
        }
        if browser is not None:
            kwargs["browser"] = browser
        if browser_context is not None:
            kwargs["browser_context"] = browser_context

        if self.system_prompt_class is not None:
            kwargs["system_prompt_class"] = self.system_prompt_class
        if self.include_attributes is not None:
            kwargs["include_attributes"] = self.include_attributes
        if self.save_conversation_path is not None:
            kwargs["save_conversation_path"] = self.save_conversation_path

        return Agent(**kwargs)  # type: ignore[arg-type]

    def get_llm_metadata(self) -> tuple[str, str]:
        return self.link.provider, self.link.model
