from collections.abc import Callable

from browser_use.llm.base import BaseChatModel as BrowserUseChatModel
from langchain_core.language_models.chat_models import (
    BaseChatModel as LangChainBaseChatModel,
)

from pirlo.core.models.link import (
    ApiKeyLink,
    AzureOpenAiLink,
    BedrockLink,
    LlmLink,
)

LANGCHAIN_BUILDERS: dict[type[LlmLink], Callable[..., LangChainBaseChatModel]] = {}
BROWSER_USE_BUILDERS: dict[type[LlmLink], Callable[..., BrowserUseChatModel]] = {}


def register_langchain_builder(link_cls: type[LlmLink]):
    """Decorator to register a LangChain LLM builder for an LlmLink type."""

    def decorator(fn: Callable[..., LangChainBaseChatModel]):
        LANGCHAIN_BUILDERS[link_cls] = fn
        return fn

    return decorator


def register_browser_use_builder(link_cls: type[LlmLink]):
    """Decorator to register a Browser-Use LLM builder for an LlmLink type."""

    def decorator(fn: Callable[..., BrowserUseChatModel]):
        BROWSER_USE_BUILDERS[link_cls] = fn
        return fn

    return decorator


# --- LangChain LLM Builders ---


@register_langchain_builder(ApiKeyLink)
def _build_api_key_langchain(
    link: ApiKeyLink,
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


@register_langchain_builder(BedrockLink)
def _build_bedrock_langchain(
    link: BedrockLink,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    max_retries: int = 3,
    timeout: float = 30.0,
    seed: int | None = None,
    extra_headers: dict | None = None,
) -> LangChainBaseChatModel:
    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError as e:
        raise ImportError(
            "The 'langchain-aws' package is required to use BedrockLink. "
            "Please install it using 'pip install langchain-aws'."
        ) from e
    kwargs: dict = {
        "model_id": link.model,
        "aws_access_key_id": link.aws_access_key_id,
        "aws_secret_access_key": link.aws_secret_access_key,
        "region_name": link.aws_region,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    llm = ChatBedrockConverse(**kwargs)
    object.__setattr__(llm, "provider", "bedrock")
    object.__setattr__(llm, "model", link.model)
    object.__setattr__(llm, "model_name", link.model)
    return llm


@register_langchain_builder(AzureOpenAiLink)
def _build_azure_langchain(
    link: AzureOpenAiLink,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    max_retries: int = 3,
    timeout: float = 30.0,
    seed: int | None = None,
    extra_headers: dict | None = None,
) -> LangChainBaseChatModel:
    from langchain_openai import AzureChatOpenAI

    kwargs: dict = {
        "azure_deployment": link.model,
        "api_key": link.api_key,
        "azure_endpoint": link.azure_endpoint,
        "api_version": link.api_version,
        "temperature": temperature,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if seed is not None:
        kwargs["seed"] = seed
    if extra_headers is not None:
        kwargs["default_headers"] = extra_headers

    llm = AzureChatOpenAI(**kwargs)
    object.__setattr__(llm, "provider", "azure")
    object.__setattr__(llm, "model", link.model)
    object.__setattr__(llm, "model_name", link.model)
    return llm


# --- Browser-Use LLM Builders ---


@register_browser_use_builder(ApiKeyLink)
def _build_api_key_browser_use(
    link: ApiKeyLink,
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


@register_browser_use_builder(AzureOpenAiLink)
def _build_azure_browser_use(
    link: AzureOpenAiLink,
    temperature: float = 0.0,
    timeout: float = 30.0,
) -> BrowserUseChatModel:
    from browser_use.llm.openai.chat import ChatOpenAI as BUOpenAI

    return BUOpenAI(
        model=link.model,
        api_key=link.api_key,
        base_url=f"{link.azure_endpoint.rstrip('/')}/openai/deployments/{link.model}",
        temperature=temperature,
        timeout=timeout,
    )


# --- Public Factory Interface ---


class LlmFactory:
    """Factory for creating LLMs via registry lookup."""

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
        builder = LANGCHAIN_BUILDERS.get(type(link))
        if not builder:
            raise ValueError(
                f"No LangChain LLM builder registered for link type '{type(link).__name__}'"
            )
        return builder(
            link,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=timeout,
            seed=seed,
            extra_headers=extra_headers,
        )

    @staticmethod
    def create_browser_use_llm(
        link: LlmLink,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> BrowserUseChatModel:
        builder = BROWSER_USE_BUILDERS.get(type(link))
        if not builder:
            raise ValueError(
                f"No Browser-Use LLM builder registered for link type '{type(link).__name__}'"
            )
        return builder(link, temperature=temperature, timeout=timeout)
