import asyncio
import logging
import time

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class ResilientPageWaiter:
    """Encapsulates page load synchronization and text settling strategies for Playwright."""

    def __init__(self, page: Page):
        self.page = page

    async def wait_for_load(self, timeout_ms: int = 5000) -> None:
        """Resiliently waits for the page DOM to be parsed."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.debug(
                f"Resilient wait_for_load_state timed out or failed: {e}",
                exc_info=True,
            )

    async def wait_for_text_settled(
        self,
        max_wait_sec: float = 10.0,
        check_interval_sec: float = 0.5,
        required_stable_cycles: int = 2,
    ) -> None:
        """Waits for page body text content to stabilize before reading text or extracting data."""
        try:
            start_time = time.time()
            prev_len = -1
            stable_cycles = 0

            while (time.time() - start_time) < max_wait_sec:
                page_text = await self.page.locator("body").inner_text()
                curr_len = len(page_text)

                if curr_len == prev_len and curr_len > 0:
                    stable_cycles += 1
                    if stable_cycles >= required_stable_cycles:
                        logger.debug("Page text content settled successfully.")
                        return
                else:
                    stable_cycles = 0
                    prev_len = curr_len

                await asyncio.sleep(check_interval_sec)
        except Exception as e:
            logger.debug(
                f"Text settling check completed or timed out: {e}",
                exc_info=True,
            )
