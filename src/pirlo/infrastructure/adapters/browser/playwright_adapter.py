import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from playwright.async_api import Locator, Page

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
from pirlo.infrastructure.adapters.browser.content_sanitizer import (
    PageContentSanitizer,
)
from pirlo.infrastructure.adapters.browser.locator_resolver import (
    ResilientLocatorResolver,
)
from pirlo.infrastructure.adapters.browser.page_waiter import ResilientPageWaiter

logger = logging.getLogger("workflow_replay.playwright_adapter")


class PlaywrightAdapter:
    """Executes domain actions against a Playwright Page instance with resilience and safety checks."""

    page: Page
    locator_resolver: ResilientLocatorResolver
    page_waiter: ResilientPageWaiter
    content_sanitizer: PageContentSanitizer
    last_extraction_result: str | None
    live_results: list[str]

    def __init__(
        self,
        page: Page,
        locator_resolver: ResilientLocatorResolver | None = None,
        page_waiter: ResilientPageWaiter | None = None,
        content_sanitizer: PageContentSanitizer | None = None,
    ) -> None:
        self.page = page
        self.locator_resolver = locator_resolver or ResilientLocatorResolver(
            page, timeout_ms=3000
        )
        self.page_waiter = page_waiter or ResilientPageWaiter(page)
        self.content_sanitizer = content_sanitizer or PageContentSanitizer()
        self.last_extraction_result = None
        self.live_results = []

    async def execute_workflow(
        self,
        workflow: Workflow,
        on_step_update: Callable[[int, Action], Coroutine[Any, Any, None]]
        | None = None,
    ) -> None:
        """Iterates through and executes all actions in a Workflow sequence."""
        from datetime import UTC, datetime

        from pirlo.core.models.actions import ActionStatus

        # Reset all steps first
        for idx, action in enumerate(workflow.actions):
            action.step_number = idx + 1
            action.status = ActionStatus.NOT_STARTED
            action.started_at = None
            action.finished_at = None
            if on_step_update:
                await on_step_update(action.step_number, action)

        for step_idx, action in enumerate(workflow.actions):
            step_num = step_idx + 1
            action.status = ActionStatus.RUNNING
            action.started_at = datetime.now(UTC)
            if on_step_update:
                await on_step_update(step_num, action)

            # Print description of the step if available
            if action.goal:
                logger.info(
                    f"Replaying step {step_num}/{len(workflow.actions)}: {action.action_type} | Goal: {action.goal}"
                )
            else:
                logger.info(
                    f"Replaying step {step_num}/{len(workflow.actions)}: {action.action_type}"
                )

            try:
                # 1. Perform live safety checks using Domain object rules
                candidate = await self._to_safety_candidate(action)
                action.check_safety_rules(candidate)

                # 2. Perform the execution
                await self.execute_action(action)
                action.status = ActionStatus.COMPLETED
                action.finished_at = datetime.now(UTC)
                if on_step_update:
                    await on_step_update(step_num, action)
            except Exception as e:
                action.status = ActionStatus.FAILED
                action.finished_at = datetime.now(UTC)
                if on_step_update:
                    await on_step_update(step_num, action)
                logger.error(
                    f"Execution failed at step {step_num}/{len(workflow.actions)} "
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
        await self.page_waiter.wait_for_load()

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
                locator = await self.locator_resolver.resolve(context)
                try:
                    await locator.click(timeout=3000)
                except Exception as e:
                    logger.warning(
                        f"Playwright standard click failed ({e}); falling back to JS executor click.",
                        exc_info=True,
                    )
                    await locator.evaluate("(el) => el.click()")
                await self._wait_for_load()
                self.live_results.append(f"Clicked element at XPath '{context.xpath}'.")

            case InputTextAction(element_context=context, text=text):
                locator = await self.locator_resolver.resolve(context, for_input=True)
                try:
                    await locator.fill("")
                    await locator.type(text)
                except Exception as fill_err:
                    logger.warning(
                        f"Standard fill failed for XPath '{context.xpath}' ({fill_err}); "
                        "focusing element and typing with keyboard.",
                        exc_info=True,
                    )
                    try:
                        await locator.focus()
                    except Exception as focus_err:
                        logger.warning(
                            f"Focus prior to typing failed: {focus_err}",
                            exc_info=True,
                        )
                    await self.page.keyboard.type(text)
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

            case ExtractContentAction():
                logger.info("Capturing live page text content snapshot...")
                await self.page_waiter.wait_for_text_settled()
                self.last_extraction_result = (
                    await self.content_sanitizer.extract_markdown(self.page)
                )
                self.live_results.append(
                    f"Captured page content snapshot ({len(self.last_extraction_result)} chars)."
                )

            case DoneAction():
                if self.last_extraction_result is not None:
                    action.text = self.last_extraction_result
                else:
                    await self.page_waiter.wait_for_text_settled()
                    action.text = await self.content_sanitizer.extract_markdown(
                        self.page
                    )
                logger.info(
                    f"DoneAction encountered: captured {len(action.text)} chars."
                )

            case _:
                raise TypeError(f"Unrecognized action subclass type: {type(action)}")
