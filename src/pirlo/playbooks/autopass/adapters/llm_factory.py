from browser_use.llm.base import BaseChatModel as BrowserUseChatModel
from langchain_core.language_models.chat_models import (
    BaseChatModel as LangChainBaseChatModel,
)

from pirlo.core.models.link import LlmLink


class LlmFactory:
    """Factory for creating LLMs for LangChain and Browser-use."""

    @staticmethod
    def create_langchain_llm(
        link: LlmLink,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        seed: int | None = None,
        extra_headers: dict | None = None,
    ) -> LangChainBaseChatModel:
        provider = link.provider.lower()
        from pirlo.playbooks.autopass.providers import SUPPORTED_PROVIDERS

        base_url = link.base_url
        if not base_url and provider in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[provider].get("default_base_url")

        kwargs: dict = {
            "temperature": temperature,
            "timeout": timeout,
            "max_retries": max_retries,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            kwargs["google_api_key"] = link.api_key
            kwargs["model"] = link.model
            llm = ChatGoogleGenerativeAI(**kwargs)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs["api_key"] = link.api_key
            kwargs["model"] = link.model
            llm = ChatAnthropic(**kwargs)
        else:  # OpenAI, DashScope, OpenAI-compatible
            from langchain_openai import ChatOpenAI

            kwargs["api_key"] = link.api_key
            kwargs["model"] = link.model
            kwargs["base_url"] = base_url
            if seed is not None:
                kwargs["seed"] = seed
            if extra_headers is not None:
                kwargs["default_headers"] = extra_headers
            llm = ChatOpenAI(**kwargs)

        object.__setattr__(llm, "provider", provider)
        object.__setattr__(llm, "model", link.model)
        object.__setattr__(llm, "model_name", link.model)
        return llm

    @staticmethod
    def create_browser_use_llm(
        link: LlmLink,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> BrowserUseChatModel:
        provider = link.provider.lower()
        from pirlo.playbooks.autopass.providers import SUPPORTED_PROVIDERS

        base_url = link.base_url
        if not base_url and provider in SUPPORTED_PROVIDERS:
            base_url = SUPPORTED_PROVIDERS[provider].get("default_base_url")

        if provider == "google":
            from browser_use.llm.google.chat import ChatGoogle

            return ChatGoogle(
                model=link.model,
                api_key=link.api_key or None,
                temperature=temperature,
            )
        elif provider == "anthropic":
            from browser_use.llm.anthropic.chat import ChatAnthropic as BUAnthropic

            return BUAnthropic(
                model=link.model,
                api_key=link.api_key or None,
                temperature=temperature,
            )
        else:
            from browser_use.llm.openai.chat import ChatOpenAI as BUOpenAI

            return BUOpenAI(
                model=link.model,
                api_key=link.api_key or None,
                base_url=base_url or None,
                temperature=temperature,
                timeout=timeout,
            )
