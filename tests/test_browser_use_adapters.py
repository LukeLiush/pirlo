from typing import Any
from unittest.mock import patch

import pytest

from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.browser.browser_use_adapters import (
    AnthropicChatModelAdapter,
    BrowserUseAdapterRegistry,
    GoogleChatModelAdapter,
    OpenAIChatModelAdapter,
    register_browser_use_adapter,
)


def test_registry_lookup():
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("google"), GoogleChatModelAdapter
    )
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("gemini"), GoogleChatModelAdapter
    )
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("anthropic"),
        AnthropicChatModelAdapter,
    )
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("openai"), OpenAIChatModelAdapter
    )
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("dashscope"),
        OpenAIChatModelAdapter,
    )
    # Fallback to OpenAI-compatible
    assert isinstance(
        BrowserUseAdapterRegistry.get_adapter("custom_unknown"),
        OpenAIChatModelAdapter,
    )


def test_decorator_validation_empty_providers():
    with pytest.raises(ValueError, match="At least one non-empty provider"):

        @register_browser_use_adapter()
        class InvalidAdapter:
            def convert(self, link: LlmLink, **kwargs: Any):
                pass


def test_decorator_validation_missing_convert():
    with pytest.raises(TypeError, match="must define a callable 'convert'"):

        @register_browser_use_adapter("dummy")
        class NoConvertAdapter:
            pass


def test_decorator_validation_missing_llmlink_hint():
    with pytest.raises(TypeError, match="annotated with type 'LlmLink'"):

        @register_browser_use_adapter("dummy")
        class BadHintAdapter:
            def convert(self, x: int) -> None:
                pass


@patch("browser_use.llm.google.chat.ChatGoogle")
def test_google_adapter_convert(mock_chat_google):
    link = LlmLink(
        name="google", provider="gemini", model="gemini-2.5-flash", api_key="test_key"
    )
    adapter = GoogleChatModelAdapter()
    adapter.convert(link, temperature=0.5)

    mock_chat_google.assert_called_once_with(
        model="gemini-2.5-flash",
        api_key="test_key",
        temperature=0.5,
    )


@patch("browser_use.llm.openai.chat.ChatOpenAI")
def test_openai_adapter_convert(mock_chat_openai):
    link = LlmLink(name="openai", provider="openai", model="gpt-4o", api_key="sk-test")
    adapter = OpenAIChatModelAdapter()
    adapter.convert(link, timeout=45.0)

    mock_chat_openai.assert_called_once_with(
        model="gpt-4o",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        timeout=45.0,
    )
