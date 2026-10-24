from typing import Any

from pirlo.core.models.link import LlmLink


class PydanticAiAdapterRegistry:
    """Factory for converting LlmLink instances into PydanticAI Model instances cleanly without side effects."""

    @classmethod
    def to_model(cls, link: LlmLink, model: str | None = None) -> Any:
        model_name = link.resolve_model(model)
        if link.base_url:
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider

            endpoint = link.base_url.rstrip("/")
            if not endpoint.endswith("/v1"):
                endpoint = f"{endpoint}/v1"
            provider = OpenAIProvider(
                base_url=endpoint, api_key=link.api_key or "ollama"
            )
            return OpenAIModel(model_name, provider=provider)

        provider_name = link.provider.lower()
        if provider_name in ("google", "gemini"):
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider

            google_provider: Any = GoogleProvider(api_key=link.api_key or None)
            return GoogleModel(model_name, provider=google_provider)

        if provider_name == "openai":
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider

            openai_provider = OpenAIProvider(api_key=link.api_key or None)
            return OpenAIModel(model_name, provider=openai_provider)

        if provider_name == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            anthropic_provider = AnthropicProvider(api_key=link.api_key or None)
            return AnthropicModel(model_name, provider=anthropic_provider)

        from pydantic_ai.models import infer_model

        return infer_model(model_name)
