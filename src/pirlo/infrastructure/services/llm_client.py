import logging
from typing import Any

import litellm

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
        **kwargs: Any,
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
        **kwargs: Any,
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
