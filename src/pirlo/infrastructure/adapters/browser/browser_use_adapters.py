from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, get_type_hints

from browser_use.llm.base import BaseChatModel as BrowserUseChatModel

from pirlo.core.models.link import SUPPORTED_PROVIDERS, LlmLink

_ADAPTER_REGISTRY: dict[str, type["BrowserUseChatModelAdapter"]] = {}


def register_browser_use_adapter(
    *providers: str,
) -> Callable[[type["BrowserUseChatModelAdapter"]], type["BrowserUseChatModelAdapter"]]:
    """Decorator to register a BrowserUseChatModelAdapter for specified provider names.

    Enforces that:
    1. At least one non-empty provider string is supplied.
    2. The decorated class defines a callable 'convert' method.
    3. The 'convert' method has a parameter type-annotated as 'LlmLink'.
    """
    if not providers or any(not p.strip() for p in providers):
        raise ValueError(
            "At least one non-empty provider name must be supplied to @register_browser_use_adapter."
        )

    def decorator(
        cls: type[BrowserUseChatModelAdapter],
    ) -> type[BrowserUseChatModelAdapter]:
        if not hasattr(cls, "convert") or not callable(cls.convert):
            raise TypeError(
                f"Class '{cls.__name__}' decorated with @register_browser_use_adapter "
                f"must define a callable 'convert' method."
            )

        try:
            hints = get_type_hints(cls.convert)
            param_types = [t for p_name, t in hints.items() if p_name != "return"]
            if LlmLink not in param_types:
                raise TypeError
        except Exception as e:
            raise TypeError(
                f"Class '{cls.__name__}.convert' method signature must accept a parameter annotated with type 'LlmLink'."
            ) from e

        for p in providers:
            _ADAPTER_REGISTRY[p.lower().strip()] = cls
        return cls

    return decorator


class BrowserUseChatModelAdapter(ABC):
    """Abstract adapter interface to convert an LlmLink into a browser-use ChatModel."""

    @abstractmethod
    def convert(
        self,
        link: LlmLink,
        **kwargs: Any,
    ) -> BrowserUseChatModel:
        """Converts an LlmLink into a browser-use ChatModel with optional parameter overrides."""


@register_browser_use_adapter("google", "gemini")
class GoogleChatModelAdapter(BrowserUseChatModelAdapter):
    def convert(
        self,
        link: LlmLink,
        **kwargs: Any,
    ) -> BrowserUseChatModel:
        try:
            from browser_use.llm.google.chat import ChatGoogle
        except ImportError as e:
            raise ImportError(
                "The 'google-genai' package is required for Google browser-use links. "
                "Please install it using 'pip install google-genai'."
            ) from e

        params: dict[str, Any] = {
            "model": link.model,
            "api_key": link.api_key or None,
        }
        params.update(kwargs)
        return ChatGoogle(**params)


@register_browser_use_adapter("anthropic")
class AnthropicChatModelAdapter(BrowserUseChatModelAdapter):
    def convert(
        self,
        link: LlmLink,
        **kwargs: Any,
    ) -> BrowserUseChatModel:
        try:
            from browser_use.llm.anthropic.chat import (
                ChatAnthropic as BUAnthropic,
            )
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for Anthropic browser-use links. "
                "Please install it using 'pip install anthropic'."
            ) from e

        params: dict[str, Any] = {
            "model": link.model,
            "api_key": link.api_key or None,
        }
        params.update(kwargs)
        return BUAnthropic(**params)


@register_browser_use_adapter("openai", "dashscope")
class OpenAIChatModelAdapter(BrowserUseChatModelAdapter):
    def convert(
        self,
        link: LlmLink,
        **kwargs: Any,
    ) -> BrowserUseChatModel:
        try:
            from browser_use.llm.openai.chat import ChatOpenAI as BUOpenAI
        except ImportError as e:
            raise ImportError(
                "The 'openai' package is required for OpenAI/DashScope browser-use links. "
                "Please install it using 'pip install openai'."
            ) from e

        base_url = link.base_url
        if not base_url and link.provider.lower() in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[link.provider.lower()].get(
                "default_base_url"
            )

        params: dict[str, Any] = {
            "model": link.model,
            "api_key": link.api_key or None,
            "base_url": base_url or None,
        }
        params.update(kwargs)
        return BUOpenAI(**params)


class BrowserUseAdapterRegistry:
    """Registry that dispatches LlmLink to its registered provider adapter."""

    @classmethod
    def get_adapter(cls, provider: str) -> BrowserUseChatModelAdapter:
        provider_lower = provider.lower().strip()
        adapter_cls = _ADAPTER_REGISTRY.get(provider_lower, OpenAIChatModelAdapter)
        return adapter_cls()

    @classmethod
    def to_chat_model(
        cls,
        link: LlmLink,
        **kwargs: Any,
    ) -> BrowserUseChatModel:
        adapter = cls.get_adapter(link.provider)
        return adapter.convert(link, **kwargs)
