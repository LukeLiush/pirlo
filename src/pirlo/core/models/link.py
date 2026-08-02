from dataclasses import dataclass


@dataclass(frozen=True)
class LinkTestResult:
    """Result of testing connectivity to an LLM provider."""
    success: bool
    message: str


@dataclass
class LlmLink:
    name: str
    provider: str
    model: str

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
        }

    def get_display_fields(self) -> list[tuple[str, str]]:
        """Returns a list of (Label, Formatted Value) pairs to display in UI cards."""
        return [
            ("Model", self.model)
        ]


@dataclass
class ApiKeyLink(LlmLink):
    """Link type for standard HTTP / API Key based providers (e.g. OpenAI, DashScope, Gemini, Anthropic)."""
    api_key: str
    base_url: str | None = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["api_key"] = self.api_key
        if self.base_url is not None:
            data["base_url"] = self.base_url
        return data

    def get_display_fields(self) -> list[tuple[str, str]]:
        fields = super().get_display_fields()
        masked_key = self.api_key
        if len(masked_key) > 8:
            masked_key = masked_key[:4] + "..." + masked_key[-4:]
        else:
            masked_key = "..."
        fields.extend([
            ("API Key", masked_key),
            ("Base URL", self.base_url or "N/A")
        ])
        return fields

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ApiKeyLink":
        provider = data["provider"]
        default_model = "qwen3.6-flash" if provider == "dashscope" else (
            "gemini-1.5-flash" if provider == "gemini" else (
                "claude-3-5-haiku-20241022" if provider == "anthropic" else "gpt-4o-mini"
            )
        )
        return cls(
            name=name,
            provider=provider,
            model=data.get("model", default_model),
            api_key=data["api_key"],
            base_url=data.get("base_url"),
        )


@dataclass
class BedrockLink(LlmLink):
    """Link type for AWS Bedrock integration."""
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["aws_access_key_id"] = self.aws_access_key_id
        data["aws_secret_access_key"] = self.aws_secret_access_key
        data["aws_region"] = self.aws_region
        return data

    def get_display_fields(self) -> list[tuple[str, str]]:
        fields = super().get_display_fields()
        masked_secret = self.aws_secret_access_key
        if len(masked_secret) > 8:
            masked_secret = masked_secret[:4] + "..." + masked_secret[-4:]
        else:
            masked_secret = "..."
        fields.extend([
            ("Access Key ID", self.aws_access_key_id),
            ("Secret Access Key", masked_secret),
            ("Region", self.aws_region)
        ])
        return fields

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "BedrockLink":
        return cls(
            name=name,
            provider=data["provider"],
            model=data.get("model", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
            aws_access_key_id=data["aws_access_key_id"],
            aws_secret_access_key=data["aws_secret_access_key"],
            aws_region=data["aws_region"],
        )


@dataclass
class AzureOpenAiLink(LlmLink):
    """Link type for Azure OpenAI integration."""
    api_key: str
    azure_endpoint: str
    api_version: str

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["api_key"] = self.api_key
        data["azure_endpoint"] = self.azure_endpoint
        data["api_version"] = self.api_version
        return data

    def get_display_fields(self) -> list[tuple[str, str]]:
        fields = super().get_display_fields()
        masked_key = self.api_key
        if len(masked_key) > 8:
            masked_key = masked_key[:4] + "..." + masked_key[-4:]
        else:
            masked_key = "..."
        fields.extend([
            ("API Key", masked_key),
            ("Endpoint", self.azure_endpoint),
            ("API Version", self.api_version)
        ])
        return fields

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "AzureOpenAiLink":
        return cls(
            name=name,
            provider=data["provider"],
            model=data.get("model", "gpt-4o-mini"),
            api_key=data["api_key"],
            azure_endpoint=data["azure_endpoint"],
            api_version=data["api_version"],
        )


def deserialize_link(name: str, data: dict) -> LlmLink:
    """Deserializes JSON link configuration into the correct LlmLink subclass."""
    provider = data.get("provider", "").lower()
    if provider == "bedrock":
        return BedrockLink.from_dict(name, data)
    elif provider == "azure":
        return AzureOpenAiLink.from_dict(name, data)
    else:
        # Default fallback for standard HTTP / API Key based providers
        return ApiKeyLink.from_dict(name, data)
