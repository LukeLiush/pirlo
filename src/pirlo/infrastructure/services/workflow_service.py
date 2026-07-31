import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from browser_use.agent.views import AgentHistoryList
from browser_use.tools.views import (
    ClickElementAction as BuClickElementAction,
)
from browser_use.tools.views import (
    ClickElementActionIndexOnly as BuClickElementActionIndexOnly,
)
from browser_use.tools.views import (
    DoneAction as BuDoneAction,
)
from browser_use.tools.views import (
    ExtractAction as BuExtractPageContentAction,
)
from browser_use.tools.views import (
    GoToUrlAction as BuGoToUrlAction,
)
from browser_use.tools.views import (
    InputTextAction as BuInputTextAction,
)
from browser_use.tools.views import (
    NavigateAction as BuNavigateAction,
)
from browser_use.tools.views import (
    ScrollAction as BuScrollAction,
)
from browser_use.tools.views import (
    SearchAction as BuSearchGoogleAction,
)
from browser_use.tools.views import (
    SendKeysAction as BuSendKeysAction,
)
from pydantic import BaseModel

from pirlo.core.models.actions import (
    Action,
    ClickAction,
    DoneAction,
    ElementContext,
    ExtractContentAction,
    InputTextAction,
    NavigateAction,
    ScrollAction,
    SendKeysAction,
)
from pirlo.core.models.workflow import Workflow, WorkflowMetadata

ADJECTIVES: list[str] = [
    "speedy",
    "clever",
    "vibrant",
    "mighty",
    "jolly",
    "sneaky",
    "sleepy",
    "brave",
    "silent",
    "gentle",
    "funky",
    "happy",
    "cosmic",
    "witty",
    "bold",
]
NOUNS: list[str] = [
    "panda",
    "koala",
    "otter",
    "badger",
    "falcon",
    "fox",
    "owl",
    "dolphin",
    "squirrel",
    "rabbit",
    "panther",
    "cheetah",
    "sloth",
    "penguin",
    "lemur",
]


def generate_deterministic_id(prompt: str) -> str:
    """Generates a human-readable, deterministic workflow ID based on the task prompt hash."""
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    # Select index values based on hash chunks
    adj_idx = int(sha[0:4], 16) % len(ADJECTIVES)
    noun_idx = int(sha[4:8], 16) % len(NOUNS)
    short_hash = sha[-5:]

    return f"{ADJECTIVES[adj_idx]}-{NOUNS[noun_idx]}-{short_hash}"


logger = logging.getLogger("workflow_replay.runner")


def get_inner_action(action_model: BaseModel) -> BaseModel:
    """Recursively unpacks Pydantic wrappers to find the actual leaf browser-use action model."""

    def unpack(obj: Any) -> Any:
        if not isinstance(obj, BaseModel):
            return obj
        cls_name = obj.__class__.__name__
        known_actions = {
            "NavigateAction",
            "GoToUrlAction",
            "ClickElementAction",
            "ClickElementActionIndexOnly",
            "InputTextAction",
            "DoneAction",
            "ScrollAction",
            "SearchAction",
            "SendKeysAction",
            "ExtractAction",
            "SwitchTabAction",
        }
        if cls_name in known_actions:
            return obj
        for field_name, value in obj:
            if value is not None:
                unpacked = unpack(value)
                if unpacked and unpacked.__class__.__name__ in known_actions:
                    return unpacked
        return obj

    result = unpack(action_model)
    if isinstance(result, BaseModel):
        return result
    return action_model


def convert_history_to_workflow(
    history_list: AgentHistoryList,
    workflow_id: str,
    description: str,
    metadata: WorkflowMetadata | None = None,
) -> Workflow:
    """Converts the browser-use AgentHistoryList into a domain-pure Workflow representation."""
    domain_actions: list[Action] = []

    for step in history_list.history:
        if not step.model_output:
            continue

        actions = step.model_output.action
        interacted_elements = step.state.interacted_element
        expected_url: str = step.state.url

        # Read the agent's goal for this step
        step_goal: str | None = None
        if step.model_output.current_state:
            step_goal = step.model_output.current_state.next_goal

        for action_idx, action_model in enumerate(actions):
            inner_action = get_inner_action(action_model)
            recorded_at = datetime.now(UTC).isoformat()

            # Map element context if available
            element_info = None
            el_context: ElementContext | None = None
            if (
                action_idx < len(interacted_elements)
                and interacted_elements[action_idx]
            ):
                element_info = interacted_elements[action_idx]

            if element_info:
                attrs = element_info.attributes or {}
                tag = element_info.node_name or "unknown"
                text_val = (
                    attrs.get("text")
                    or attrs.get("value")
                    or element_info.ax_name
                    or tag
                )
                el_context = ElementContext(
                    xpath=element_info.x_path,
                    tag_name=tag,
                    text=text_val,
                    attributes=attrs,
                )

            match inner_action:
                case BuGoToUrlAction(url=url) | BuNavigateAction(url=url):
                    domain_actions.append(
                        NavigateAction(
                            url=url,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )
                case BuSearchGoogleAction(query=query):
                    google_url = f"https://www.google.com/search?q={query}&udm=14"
                    domain_actions.append(
                        NavigateAction(
                            url=google_url,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )
                case BuClickElementAction() | BuClickElementActionIndexOnly():
                    if el_context:
                        domain_actions.append(
                            ClickAction(
                                element_context=el_context,
                                expected_url=expected_url,
                                goal=step_goal,
                                recorded_at=recorded_at,
                            )
                        )
                case BuInputTextAction(text=text):
                    if el_context:
                        domain_actions.append(
                            InputTextAction(
                                element_context=el_context,
                                text=text,
                                expected_url=expected_url,
                                goal=step_goal,
                                recorded_at=recorded_at,
                            )
                        )
                case BuScrollAction(down=down, pages=pages):
                    amount = int(pages * 800) if down else -int(pages * 800)
                    domain_actions.append(
                        ScrollAction(
                            amount=amount,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )
                case BuSendKeysAction(keys=keys):
                    domain_actions.append(
                        SendKeysAction(
                            keys=keys,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )
                case BuExtractPageContentAction(extract_links=include_links):
                    domain_actions.append(
                        ExtractContentAction(
                            include_links=include_links,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )
                case BuDoneAction(text=text):
                    domain_actions.append(
                        DoneAction(
                            text=text,
                            expected_url=expected_url,
                            goal=step_goal,
                            recorded_at=recorded_at,
                        )
                    )

    if not domain_actions:
        raise RuntimeError(
            "No actions were successfully recorded during the agent's run. "
            "Please check your browser connection or verify if the target page loaded correctly."
        )
    return Workflow(
        workflow_id=workflow_id,
        description=description,
        metadata=metadata,
        actions=domain_actions,
    )
