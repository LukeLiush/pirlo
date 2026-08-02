from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from pirlo.core.models.specifications import SafetyCandidate


class ActionStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ElementContext(BaseModel):
    xpath: str
    tag_name: str | None = None
    text: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("xpath")
    @classmethod
    def validate_xpath(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("XPath selector cannot be empty.")
        # If it doesn't start with a valid prefix, prepend '/' to make it absolute
        if not (stripped.startswith(("/", "xpath=", "("))):
            stripped = "/" + stripped
        return stripped


# --- POLYMORPHIC ACTION HIERARCHY ---


class ActionBase(BaseModel):
    """Abstract base for all domain actions."""

    expected_url: str | None = None
    goal: str | None = None  # Saves the agent's goal for every step
    recorded_at: str | None = None  # ISO timestamp of the action
    step_number: int | None = None
    status: ActionStatus = ActionStatus.NOT_STARTED
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def check_safety_rules(self, candidate: "SafetyCandidate") -> None: ...


class NavigateAction(ActionBase):
    action_type: Literal["navigate"] = "navigate"
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ["http", "https"]:
            raise ValueError(f"Navigation URL must use HTTP or HTTPS scheme: '{v}'")
        if not parsed.netloc:
            raise ValueError(f"Navigation URL must specify a domain/netloc: '{v}'")
        return v


class ClickAction(ActionBase):
    action_type: Literal["click"] = "click"
    element_context: ElementContext

    def check_safety_rules(self, candidate: "SafetyCandidate") -> None:
        from pirlo.core.models.specifications import (
            ElementMutationSpecification,
            ElementTagMatchSpecification,
        )

        spec = ElementTagMatchSpecification(
            self.element_context.tag_name
        ) & ElementMutationSpecification(self.element_context.text)
        spec.is_satisfied_by(candidate)


class InputTextAction(ActionBase):
    action_type: Literal["input"] = "input"
    element_context: ElementContext
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v:
            raise ValueError("Input text value cannot be empty.")
        return v

    def check_safety_rules(self, candidate: "SafetyCandidate") -> None:
        from pirlo.core.models.specifications import (
            ElementMutationSpecification,
            ElementTagMatchSpecification,
        )

        spec = ElementTagMatchSpecification(
            self.element_context.tag_name
        ) & ElementMutationSpecification(self.element_context.text)
        spec.is_satisfied_by(candidate)


class ScrollAction(ActionBase):
    action_type: Literal["scroll"] = "scroll"
    amount: int | None = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError(f"Scroll amount must be greater than 0: {v}")
        return v


class SendKeysAction(ActionBase):
    action_type: Literal["send_keys"] = "send_keys"
    keys: str

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Key sequence cannot be empty.")
        return v


class ExtractContentAction(ActionBase):
    action_type: Literal["extract_content"] = "extract_content"
    include_links: bool = False


class DoneAction(ActionBase):
    action_type: Literal["done"] = "done"
    text: str


# Discriminator mapping for loading JSON files
Action = Annotated[
    NavigateAction
    | ClickAction
    | InputTextAction
    | ScrollAction
    | SendKeysAction
    | ExtractContentAction
    | DoneAction,
    Field(discriminator="action_type"),
]
