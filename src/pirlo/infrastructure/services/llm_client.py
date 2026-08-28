import logging

import litellm
from browser_use.llm.base import BaseChatModel as BrowserUseChatModel

from pirlo.core.models.link import SUPPORTED_PROVIDERS, LlmLink

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.ERROR)


class LlmClient:
    """Unified client for executing LLM completions across providers via LiteLLM."""

    @staticmethod
    def completion(
        link: LlmLink,
        prompt: str | list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float = 30.0,
        **kwargs,
    ) -> str:
        """Synchronously invokes LiteLLM completion for text transformation/summarization."""
        messages = (
            [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        )

        base_url = link.base_url
        provider = link.provider.lower()
        if not base_url and provider in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[provider].get("default_base_url")

        response = litellm.completion(
            model=link.model,
            custom_llm_provider=provider,
            messages=messages,
            api_key=link.api_key or None,
            api_base=base_url or None,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    async def acompletion(
        link: LlmLink,
        prompt: str | list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float = 30.0,
        **kwargs,
    ) -> str:
        """Asynchronously invokes LiteLLM completion for text transformation/summarization."""
        messages = (
            [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        )

        base_url = link.base_url
        provider = link.provider.lower()
        if not base_url and provider in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[provider].get("default_base_url")

        response = await litellm.acompletion(
            model=link.model,
            custom_llm_provider=provider,
            messages=messages,
            api_key=link.api_key or None,
            api_base=base_url or None,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def create_browser_use_llm(
        link: LlmLink,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> BrowserUseChatModel:
        """Instantiates native model objects required by browser-use Agent sessions."""
        provider = link.provider.lower()

        base_url = link.base_url
        if not base_url and provider in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[provider].get("default_base_url")

        if provider in ("google", "gemini"):
            try:
                from browser_use.llm.google.chat import ChatGoogle
            except ImportError as e:
                raise ImportError(
                    "The 'google-genai' package is required for Google browser-use LLMs. "
                    "Please install it using 'pip install google-genai'."
                ) from e

            return ChatGoogle(
                model=link.model,
                api_key=link.api_key or None,
                temperature=temperature,
            )
        elif provider == "anthropic":
            try:
                from browser_use.llm.anthropic.chat import (
                    ChatAnthropic as BUAnthropic,
                )
            except ImportError as e:
                raise ImportError(
                    "The 'anthropic' package is required for Anthropic browser-use LLMs. "
                    "Please install it using 'pip install anthropic'."
                ) from e

            return BUAnthropic(
                model=link.model,
                api_key=link.api_key or None,
                temperature=temperature,
            )
        else:
            try:
                from browser_use.llm.openai.chat import ChatOpenAI as BUOpenAI
            except ImportError as e:
                raise ImportError(
                    "The 'openai' package is required for OpenAI browser-use LLMs. "
                    "Please install it using 'pip install openai'."
                ) from e

            return BUOpenAI(
                model=link.model,
                api_key=link.api_key or None,
                base_url=base_url or None,
                temperature=temperature,
                timeout=timeout,
            )
