import logging

from playwright.async_api import Locator, Page

from pirlo.core.models.actions import ElementContext

logger = logging.getLogger(__name__)


class ResilientLocatorResolver:
    """Encapsulates multi-selector resolution strategies with fail-fast timeouts and fallbacks."""

    def __init__(self, page: Page, timeout_ms: int = 3000):
        self.page = page
        self.timeout_ms = timeout_ms

    async def resolve(self, context: ElementContext) -> Locator:
        if not context:
            raise ValueError("ElementContext is required to resolve a locator.")

        # 1. Primary XPath check (3s fail-fast timeout)
        primary_loc = self.page.locator(f"xpath={context.xpath}").first
        try:
            await primary_loc.wait_for(state="attached", timeout=self.timeout_ms)
            return primary_loc
        except Exception as e:
            logger.warning(
                f"Primary XPath '{context.xpath}' not found or timed out ({self.timeout_ms}ms). "
                f"Attempting resilient fallbacks... (Error: {e})",
                exc_info=True,
            )

        # 2. Text / ARIA Name Fallback
        if context.text and len(context.text.strip()) > 1:
            clean_text = context.text.strip()
            try:
                text_loc = self.page.get_by_text(clean_text, exact=False).first
                if await text_loc.count() > 0:
                    logger.info(
                        f"Resilient locator fallback succeeded: matched text '{clean_text}'"
                    )
                    return text_loc
            except Exception as e:
                logger.warning(
                    f"Text fallback check failed for '{clean_text}': {e}",
                    exc_info=True,
                )

        # 3. Attribute Fallback (href, id, placeholder, name, aria-label, title)
        attrs = context.attributes or {}
        tag = (
            context.tag_name
            if context.tag_name and context.tag_name != "unknown"
            else "*"
        )
        for attr_key in ("href", "id", "placeholder", "name", "aria-label", "title"):
            if attrs.get(attr_key):
                attr_val = attrs[attr_key]
                if attr_key == "href" and len(attr_val) > 5:
                    css_selector = f"{tag}[href*='{attr_val}']"
                elif attr_key == "id":
                    css_selector = f"{tag}#{attr_val}"
                else:
                    css_selector = f"{tag}[{attr_key}='{attr_val}']"

                try:
                    attr_loc = self.page.locator(css_selector).first
                    if await attr_loc.count() > 0:
                        logger.info(
                            f"Resilient locator fallback succeeded: matched CSS '{css_selector}'"
                        )
                        return attr_loc
                except Exception as e:
                    logger.warning(
                        f"Attribute fallback check failed for '{css_selector}': {e}",
                        exc_info=True,
                    )

        # Default fallback to primary locator
        return primary_loc
