from dataclasses import dataclass


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

    def to_dict(self) -> dict:
        data: dict[str, str] = {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
        }
        if self.base_url:
            data["base_url"] = self.base_url
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "LlmLink":
        return cls(
            name=name,
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url"),
        )
