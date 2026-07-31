import asyncio
import logging
from typing import Any

import httpx
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from playwright.async_api import Locator, Page


def is_timeout_exception(e: Exception) -> bool:
    """Determines if the exception is an explicit or implicit timeout error."""
    if isinstance(e, (httpx.TimeoutException, openai.APITimeoutError, TimeoutError)):
        return True
    return "timeout" in str(e).lower()


from pirlo.core.models.actions import (
    Action,
    ClickAction,
    DoneAction,
    ExtractContentAction,
    InputTextAction,
    NavigateAction,
    ScrollAction,
    SendKeysAction,
)
from pirlo.core.models.specifications import SafetyCandidate
from pirlo.core.models.workflow import Workflow

logger = logging.getLogger("workflow_replay.playwright_adapter")


class PlaywrightAdapter:
    """Infrastructure adapter that translates domain Actions to Playwright execution steps."""

    page: Page
    llm: BaseChatModel | None
    last_extraction_result: str | None
    live_results: list[str]

    def __init__(self, page: Page, llm: BaseChatModel | None = None) -> None:
        self.page = page
        self.llm = llm
        self.last_extraction_result = None
        self.live_results = []

    async def execute_workflow(self, workflow: Workflow) -> None:
        """Iterates through and executes all actions in a Workflow sequence."""
        for step_idx, action in enumerate(workflow.actions):
            # Print description of the step if available
            if action.goal:
                logger.info(
                    f"Replaying step {step_idx + 1}/{len(workflow.actions)}: {action.action_type} | Goal: {action.goal}"
                )
            else:
                logger.info(
                    f"Replaying step {step_idx + 1}/{len(workflow.actions)}: {action.action_type}"
                )

            try:
                # 1. Perform live safety checks using Domain object rules
                candidate = await self._to_safety_candidate(action)
                action.check_safety_rules(candidate)

                # 2. Perform the execution
                await self.execute_action(action)
            except Exception as e:
                logger.error(
                    f"Execution failed at step {step_idx + 1}/{len(workflow.actions)} "
                    f"[{action.action_type.upper()} action]. "
                    f"Action goal: '{action.goal or 'none'}'. "
                    f"Error details: {e}"
                )
                raise

            # Brief delay between steps
            await asyncio.sleep(1.0)

    async def _to_safety_candidate(self, action: Action) -> SafetyCandidate:
        """Gathers the live page state and builds a SafetyCandidate for rule checking."""
        live_url: str = self.page.url
        live_element_info: dict[str, Any] | None = None

        if hasattr(action, "element_context") and action.element_context:
            xpath: str = action.element_context.xpath
            live_element_info = await self._fetch_live_element_info(xpath)

        return SafetyCandidate(
            action=action, live_url=live_url, live_element_info=live_element_info
        )

    async def _fetch_live_element_info(self, xpath: str) -> dict[str, Any] | None:
        """Fetches the live element details (tag name, inner text, attributes) from the page."""
        locator: Locator = self.page.locator(f"xpath={xpath}").first
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)

            # Read DOM signature for verification
            tag_name: str = await locator.evaluate("el => el.tagName")
            text: str = await locator.inner_text()
            attrs: dict[str, str] = await locator.evaluate("""el => {
                let a = {};
                for (let attr of el.attributes) {
                    a[attr.name] = attr.value;
                }
                return a;
            }""")

            return {"tag_name": tag_name, "text": text, "attributes": attrs}
        except Exception as locator_err:  # noqa: BLE001
            logger.debug(
                f"Could not fetch element details for xpath '{xpath}': {locator_err}"
            )
            return None

    async def _wait_for_load(self) -> None:
        """Resiliently waits for the page DOM to be parsed with a short timeout."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001, S110
            pass

    async def execute_action(self, action: Action) -> None:
        """Translates a single domain action to a Playwright page interaction."""
        match action:
            case NavigateAction(url=url):
                try:
                    await self.page.goto(
                        url, wait_until="domcontentloaded", timeout=15000
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"Resilient navigation timeout or error: {e}")
                await self._wait_for_load()
                self.live_results.append(f"Navigated to '{url}' successfully.")

            case ClickAction(element_context=context):
                locator = self.page.locator(f"xpath={context.xpath}").first
                try:
                    await locator.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    # JS fallback click if click is obstructed
                    logger.debug(
                        "Playwright standard click failed; falling back to JS executor click."
                    )
                    await locator.evaluate("(el) => el.click()")
                await self._wait_for_load()
                self.live_results.append(f"Clicked element at XPath '{context.xpath}'.")

            case InputTextAction(element_context=context, text=text):
                locator = self.page.locator(f"xpath={context.xpath}").first
                await locator.fill("")
                await locator.type(text)
                await self._wait_for_load()
                self.live_results.append(
                    f"Inputted text '{text}' into element at XPath '{context.xpath}'."
                )

            case ScrollAction(amount=amount):
                if amount is not None:
                    await self.page.evaluate(f"window.scrollBy(0, {amount});")
                    self.live_results.append(f"Scrolled page by amount {amount}.")
                else:
                    await self.page.keyboard.press("PageDown")
                    self.live_results.append("Scrolled page down.")

            case SendKeysAction(keys=keys):
                await self.page.keyboard.press(keys)
                self.live_results.append(f"Sent keyboard keys '{keys}'.")

            case ExtractContentAction(include_links=_, goal=goal):
                if not self.llm:
                    raise RuntimeError(
                        "LLM is required to execute ExtractContentAction."
                    )

                logger.info("Executing LLM Data Extraction on live page content...")
                # 1. Fetch clean text of the page body
                page_text = await self.page.locator("body").inner_text()

                # 2. Instruct LLM to perform cognitive extraction from the live text
                prompt = (
                    f"You are a web data extraction assistant. Based on the page content below, "
                    f"perform the step goal: '{goal}'.\n"
                    f"Be direct and concise in your response.\n\n"
                    f"Page Content:\n{page_text}"
                )
                prompt_bytes = len(prompt.encode("utf-8"))

                try:
                    response = await self.llm.ainvoke(prompt)
                    self.last_extraction_result = str(response.content)
                    logger.info(
                        f"LLM Data Extraction completed: {self.last_extraction_result}"
                    )
                    self.live_results.append(
                        f"Extracted content: '{self.last_extraction_result}'"
                    )
                except Exception as e:
                    if is_timeout_exception(e):
                        raise RuntimeError(
                            f"LLM request timed out during content extraction. "
                            f"Exception type: '{type(e).__name__}'. Input size: {prompt_bytes} bytes. "
                            f"Please consider increasing the LLM 'timeout' configuration (e.g. timeout=120) in play_self_healing.py."
                        ) from e
                    raise

            case DoneAction(text=text, goal=goal):
                if self.llm and goal:
                    logger.info("Synthesizing final workflow result via LLM...")
                    # Fetch clean text of the page body to ensure LLM has access to the final screen state
                    page_text = await self.page.locator("body").inner_text()

                    # Construct synthesis prompt
                    prompt = (
                        f"You are completing a browser automation workflow. Your final goal is: '{goal}'.\n"
                        f"Here are the live results of the actions taken:\n"
                        f"{self.live_results}\n\n"
                        f"Current Page Content:\n{page_text}\n\n"
                        f"Provide the final direct response/answer."
                    )
                    prompt_bytes = len(prompt.encode("utf-8"))

                    try:
                        response = await self.llm.ainvoke(prompt)
                        action.text = str(response.content)
                    except Exception as e:
                        if is_timeout_exception(e):
                            raise RuntimeError(
                                f"LLM request timed out during final response synthesis. "
                                f"Exception type: '{type(e).__name__}'. Input size: {prompt_bytes} bytes. "
                                f"Please consider increasing the LLM 'timeout' configuration (e.g. timeout=120) in play_self_healing.py."
                            ) from e
                        raise
                elif self.last_extraction_result is not None:
                    action.text = self.last_extraction_result
                logger.info(f"DoneAction encountered: {action.text}")

            case _:
                raise TypeError(f"Unrecognized action subclass type: {type(action)}")
