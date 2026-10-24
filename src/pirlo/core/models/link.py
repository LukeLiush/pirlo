import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

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


class Link(ABC):
    """A named way to reach something pirlo can use, stored under its kind."""

    kind: ClassVar[str]
    name: str
    source: str | None
    is_default: bool

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Returns the persisted representation, including the kind."""

    @abstractmethod
    def to_safe_dict(self) -> dict[str, Any]:
        """Returns a display representation with sensitive fields masked."""

    @classmethod
    @abstractmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "Link":
        """Rebuilds a link of this kind from its persisted representation."""


class MissingModelError(ValueError):
    """Raised when neither the caller nor the link supplies a model."""

    def __init__(self, link_name: str) -> None:
        self.link_name = link_name
        super().__init__(
            f"No model for link '{link_name}': pass --model or set a default model on the link"
        )


@dataclass
class LlmLink(Link):
    """Represents an LLM provider connection link.

    The link identifies a provider account; the model is chosen per call, falling
    back to default_model. default_model is persisted under the "model" key.
    """

    kind: ClassVar[str] = "api"

    name: str
    provider: str
    api_key: str
    base_url: str | None = None
    default_model: str | None = None
    source: str | None = None
    is_default: bool = False

    @property
    def masked_api_key(self) -> str:
        if not self.api_key:
            return "N/A"
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}****{self.api_key[-4:]}"

    def resolve_model(self, model: str | None = None) -> str:
        """Returns the explicit model, else this link's default, else raises MissingModelError."""
        resolved = model or self.default_model
        if not resolved:
            raise MissingModelError(self.name)
        return resolved

    def __str__(self) -> str:
        base_url_str = f", base_url='{self.base_url}'" if self.base_url else ""
        source_str = f", source='{self.source}'" if self.source else ""
        return (
            f"LlmLink(name='{self.name}', provider='{self.provider}', "
            f"default_model='{self.default_model}', api_key='{self.masked_api_key}'"
            f"{base_url_str}{source_str})"
        )

    def __repr__(self) -> str:
        return (
            f"LlmLink(name={self.name!r}, provider={self.provider!r}, "
            f"default_model={self.default_model!r}, api_key={self.masked_api_key!r}, "
            f"base_url={self.base_url!r}, source={self.source!r}, "
            f"is_default={self.is_default!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return self._serialize(api_key=self.api_key)

    def to_safe_dict(self) -> dict[str, Any]:
        """Returns a dict representation with sensitive fields masked."""
        return self._serialize(api_key=self.masked_api_key)

    def _serialize(self, api_key: str) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "provider": self.provider}
        if self.default_model:
            data["model"] = self.default_model
        data["api_key"] = api_key
        if self.base_url:
            data["base_url"] = self.base_url
        if self.source:
            data["source"] = self.source
        if self.is_default:
            data["is_default"] = self.is_default
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "LlmLink":
        return cls(
            name=name,
            provider=data.get("provider", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url"),
            default_model=data.get("model") or None,
            source=data.get("source"),
            is_default=data.get("is_default", False),
        )


LINK_KINDS: dict[str, type[Link]] = {LlmLink.kind: LlmLink}


def link_from_dict(name: str, data: dict[str, Any]) -> Link | None:
    """Loads a stored link by its kind; entries without a kind are API links."""
    kind = data.get("kind", LlmLink.kind)
    link_cls = LINK_KINDS.get(kind)
    if link_cls is None:
        logger.warning("Skipping link '%s': unknown kind '%s'", name, kind)
        return None
    return link_cls.from_dict(name, data)
