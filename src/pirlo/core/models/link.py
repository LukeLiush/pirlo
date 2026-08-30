from dataclasses import dataclass
from typing import Any

SUPPORTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "dashscope": {
        "env_names": ["DASHSCOPE_API_KEY", "ALIBABA_API_KEY"],
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "gemini": {
        "env_names": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "default_base_url": None,
    },
    "openai": {
        "env_names": ["OPENAI_API_KEY"],
        "default_base_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "env_names": ["ANTHROPIC_API_KEY"],
        "default_base_url": None,
    },
    "ollama": {
        "env_names": ["OLLAMA_HOST"],
        "default_base_url": "http://localhost:11434/v1",
    },
}


@dataclass(frozen=True)
class LinkTestResult:
    """Result of testing connectivity to an LLM provider."""

    success: bool
    message: str


@dataclass
class LlmLink:
    """Represents an LLM provider connection link."""

    name: str
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    source: str | None = None

    @property
    def masked_api_key(self) -> str:
        if not self.api_key:
            return "N/A"
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}****{self.api_key[-4:]}"

    def __str__(self) -> str:
        base_url_str = f", base_url='{self.base_url}'" if self.base_url else ""
        source_str = f", source='{self.source}'" if self.source else ""
        return (
            f"LlmLink(name='{self.name}', provider='{self.provider}', "
            f"model='{self.model}', api_key='{self.masked_api_key}'{base_url_str}{source_str})"
        )

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
        }
        if self.base_url:
            data["base_url"] = self.base_url
        if self.source:
            data["source"] = self.source
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "LlmLink":
        return cls(
            name=name,
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url"),
            source=data.get("source"),
        )
