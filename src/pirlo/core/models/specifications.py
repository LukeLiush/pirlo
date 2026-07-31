from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pydantic import BaseModel

from pirlo.core.models.exception import SafetyViolationException

if TYPE_CHECKING:
    from pirlo.core.models.actions import Action


class SafetyCandidate(BaseModel):
    """Encapsulates execution context required to verify dynamic safety rules."""

    live_url: str
    live_element_info: dict[str, Any] | None = None
    action: "Action | None" = None


class Specification(ABC):
    """Abstract base representing a combinable domain specification using operator overloading."""

    @abstractmethod
    def is_satisfied_by(self, candidate: Any) -> bool:
        """Evaluates the specification against a candidate. Raises SafetyViolationException on failure."""

    def __and__(self, other: "Specification") -> "Specification":
        return AndSpecification(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return OrSpecification(self, other)

    def __invert__(self) -> "Specification":
        return NotSpecification(self)


class AndSpecification(Specification):
    spec_a: Specification
    spec_b: Specification

    def __init__(self, spec_a: Specification, spec_b: Specification) -> None:
        self.spec_a = spec_a
        self.spec_b = spec_b

    def is_satisfied_by(self, candidate: Any) -> bool:
        return self.spec_a.is_satisfied_by(candidate) and self.spec_b.is_satisfied_by(
            candidate
        )


class OrSpecification(Specification):
    spec_a: Specification
    spec_b: Specification

    def __init__(self, spec_a: Specification, spec_b: Specification) -> None:
        self.spec_a = spec_a
        self.spec_b = spec_b

    def is_satisfied_by(self, candidate: Any) -> bool:
        return self.spec_a.is_satisfied_by(candidate) or self.spec_b.is_satisfied_by(
            candidate
        )


class NotSpecification(Specification):
    spec: Specification

    def __init__(self, spec: Specification) -> None:
        self.spec = spec

    def is_satisfied_by(self, candidate: Any) -> bool:
        return not self.spec.is_satisfied_by(candidate)


# --- CONCRETE SAFETY SPECIFICATIONS ---


class DomainBoundarySpecification(Specification):
    """Verifies that the live URL domain complies with whitelist/blacklist boundaries."""

    allowlist: set[str]
    blacklist: set[str]

    def __init__(
        self, allowlist: list[str] | None = None, blacklist: list[str] | None = None
    ) -> None:
        self.allowlist = set(allowlist) if allowlist else set()
        self.blacklist = set(blacklist) if blacklist else set()

        # Validate disjoint sets
        overlap = self.allowlist.intersection(self.blacklist)
        if overlap:
            raise ValueError(
                f"Configuration conflict: Domains {overlap} cannot exist "
                f"in both allowlist and blacklist."
            )

    def is_satisfied_by(self, candidate: SafetyCandidate) -> bool:
        live_url = candidate.live_url
        if live_url == "about:blank":
            return True

        live_netloc = urlparse(live_url).netloc
        if not live_netloc:
            return True

        # 1. Check blacklist
        if any(
            live_netloc == blocked or live_netloc.endswith("." + blocked)
            for blocked in self.blacklist
        ):
            raise SafetyViolationException(
                f"Safety violation: Banned domain '{live_netloc}' accessed."
            )

        # 2. Check allowlist
        if self.allowlist and not any(
            live_netloc == allowed or live_netloc.endswith("." + allowed)
            for allowed in self.allowlist
        ):
            raise SafetyViolationException(
                f"Safety violation: Out of boundary domain '{live_netloc}' accessed."
            )

        return True


class ElementTagMatchSpecification(Specification):
    """Verifies that the live HTML element tag corresponds with the recorded tag name."""

    expected_tag: str | None

    def __init__(self, expected_tag: str | None = None) -> None:
        self.expected_tag = expected_tag

    def is_satisfied_by(self, candidate: SafetyCandidate) -> bool:
        if self.expected_tag and candidate.live_element_info:
            live_tag: str = candidate.live_element_info.get("tag_name", "").lower()
            expected_tag_lower = self.expected_tag.lower()
            if live_tag != expected_tag_lower:
                raise SafetyViolationException(
                    f"Element tag mismatch: Expected tag '{expected_tag_lower}', but live tag is '{live_tag}'."
                )
        return True


class ElementMutationSpecification(Specification):
    """Safeguards against dynamic text mutations mutating into destructive actions (e.g. 'delete')."""

    recorded_text: str | None

    def __init__(self, recorded_text: str | None = None) -> None:
        self.recorded_text = recorded_text

    def is_satisfied_by(self, candidate: SafetyCandidate) -> bool:
        if candidate.live_element_info:
            live_text: str = candidate.live_element_info.get("text", "").lower()
            blocklist: list[str] = ["delete", "pay", "buy", "purchase", "remove"]
            if any(term in live_text for term in blocklist):
                original_text: str = (self.recorded_text or "").lower()
                if not any(term in original_text for term in blocklist):
                    raise SafetyViolationException(
                        f"Unsafe element mutation: Recorded element was safe, "
                        f"but live element text is now sensitive: '{live_text}'"
                    )
        return True
