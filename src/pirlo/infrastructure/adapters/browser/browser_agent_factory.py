import os
from pathlib import Path
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

from browser_use import Agent, Browser, Controller
from browser_use.agent.prompts import SystemPrompt

from pirlo.core.ports.browser_agent_factory import BrowserAgentFactory


class DefaultBrowserAgentFactory(BrowserAgentFactory):
    def __init__(
        self,
        llm: Any,
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
        """
        Factory to construct configured browser-use Agent sessions.

        Args:
            llm (BaseChatModel):
                The LangChain chat model used for reasoning, planning, and action selection.
            controller (Optional[Controller], optional):
                The custom tools registry. Registering custom Python functions here allows
                the agent to run custom actions beyond standard browser interactions. Defaults to None.
            use_vision (bool, optional):
                Toggles screenshot processing. True allows the model to process images, which
                improves accuracy on visual-heavy elements, but increases token costs and latency. Defaults to False.
            system_prompt_class (Optional[Type[SystemPrompt]], optional):
                Custom SystemPrompt template override, allowing custom guidelines, safety policies,
                or output restrictions. Defaults to None.
            include_attributes (Optional[List[str]], optional):
                List of DOM node attributes serialized and sent to the LLM (e.g. data-testid for tests).
                Defaults to None.
            max_failures (int, optional):
                Maximum consecutive action failures (e.g., element not found, parse errors) tolerated
                before the agent stops execution. Defaults to 5.
            retry_delay (int, optional):
                Delay in seconds between retrying a failed step. Defaults to 10.
            generate_gif (Union[bool, str, Path], optional):
                Whether to capture screenshots and generate a GIF recording, or path to destination GIF file. Defaults to False.
            max_actions_per_step (int, optional):
                Maximum actions the agent can output in a single model turn. Lower numbers reduce cascades
                of wrong actions. Defaults to 10.
            save_conversation_path (Optional[str], optional):
                Path to output a JSON formatted file containing the complete history/run trace. Defaults to None.
        """
        self.llm = llm
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

    def create_agent(self, task: str, browser: Browser) -> Agent:
        kwargs = {
            "task": task,
            "llm": self.llm,
            "browser": browser,
            "controller": self.controller,
            "use_vision": self.use_vision,
            "max_failures": self.max_failures,
            "retry_delay": self.retry_delay,
            "generate_gif": self.generate_gif,
            "max_actions_per_step": self.max_actions_per_step,
        }
        if self.system_prompt_class is not None:
            kwargs["system_prompt_class"] = self.system_prompt_class
        if self.include_attributes is not None:
            kwargs["include_attributes"] = self.include_attributes
        if self.save_conversation_path is not None:
            kwargs["save_conversation_path"] = self.save_conversation_path

        return Agent(**kwargs)  # type: ignore[arg-type]

    def get_llm_metadata(self) -> tuple[str, str]:
        provider = self.llm.__class__.__name__
        model = getattr(self.llm, "model_name", getattr(self.llm, "model", "unknown"))
        return provider, model
