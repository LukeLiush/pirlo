from pathlib import Path
from unittest.mock import MagicMock

from pirlo.infrastructure.adapters.browser.browser_agent_factory import (
    DefaultBrowserAgentFactory,
)


def test_default_browser_agent_factory_gif_defaults():
    llm = MagicMock()
    factory = DefaultBrowserAgentFactory(llm=llm)
    assert factory.generate_gif is False


def test_default_browser_agent_factory_gif_boolean():
    llm = MagicMock()
    factory = DefaultBrowserAgentFactory(llm=llm, generate_gif=True)
    assert factory.generate_gif is True


def test_default_browser_agent_factory_generate_gif_str_path():
    llm = MagicMock()
    gif_file = "/tmp/pirlo_runs/run_123/agent_history.gif"

    factory = DefaultBrowserAgentFactory(
        llm=llm,
        generate_gif=gif_file,
    )
    assert factory.generate_gif == gif_file


def test_default_browser_agent_factory_generate_gif_as_path_object():
    llm = MagicMock()
    gif_file = Path("/tmp/pirlo_runs/run_456/custom_history.gif")

    factory = DefaultBrowserAgentFactory(
        llm=llm,
        generate_gif=gif_file,
    )
    assert factory.generate_gif == str(gif_file)
