import logging
import re

from playwright.async_api import Page

logger = logging.getLogger("workflow_replay.content_sanitizer")

DEFAULT_NOISE_SELECTORS: tuple[str, ...] = (
    "nav",
    "footer",
    "header",
    "script",
    "style",
    "iframe",
    "noscript",
    "svg",
    '[aria-hidden="true"]',
    ".cookie-banner",
    "#comments",
    ".ad-container",
)

DEFAULT_MAIN_SELECTORS: tuple[str, ...] = (
    "main",
    "article",
    '[role="main"]',
    "#content",
    "#main-content",
)


class PageContentSanitizer:
    """Domain component that prunes DOM noise and converts HTML content into clean Markdown."""

    noise_selectors: tuple[str, ...]
    main_selectors: tuple[str, ...]

    def __init__(
        self,
        noise_selectors: tuple[str, ...] | None = None,
        main_selectors: tuple[str, ...] | None = None,
    ) -> None:
        self.noise_selectors = noise_selectors or DEFAULT_NOISE_SELECTORS
        self.main_selectors = main_selectors or DEFAULT_MAIN_SELECTORS

    async def prune_dom_noise(self, page: Page) -> None:
        """Removes non-essential noise elements (nav, footer, script, ads) from page DOM."""
        if not self.noise_selectors:
            return
        selector_str = ", ".join(self.noise_selectors)
        try:
            await page.evaluate(
                """(selector) => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                }""",
                selector_str,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"DOM noise pruning encountered non-fatal error: {e}")

    async def extract_markdown(self, page: Page) -> str:
        """Prunes DOM noise and converts main page HTML to condensed Markdown."""
        await self.prune_dom_noise(page)

        # Extract HTML from priority main container, fallback to body
        html_content: str = ""
        if self.main_selectors:
            combined_main_selector = ", ".join(self.main_selectors)
            main_locator = page.locator(combined_main_selector).first
            try:
                if await main_locator.count() > 0:
                    html_content = await main_locator.inner_html()
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    f"Main container extraction encountered non-fatal error: {e}"
                )

        if not html_content:
            try:
                html_content = await page.locator("body").inner_html()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Body inner HTML fallback error: {e}")
                html_content = ""

        # Convert to Markdown
        try:
            import html2text

            converter = html2text.HTML2Text()
            converter.ignore_links = True
            converter.ignore_images = True
            converter.body_width = 0

            text = converter.handle(html_content) if html_content else ""
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Markdown conversion fallback to inner_text: {e}")
            try:
                text = await page.locator("body").inner_text()
            except Exception as e_inner:  # noqa: BLE001
                logger.debug(f"Body inner text fallback error: {e_inner}")
                text = ""

        # Collapse whitespace and empty lines
        lines = [line.strip() for line in text.splitlines()]
        cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return cleaned
