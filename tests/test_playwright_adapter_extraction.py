import unittest
from unittest.mock import AsyncMock, MagicMock

from pirlo.core.models.actions import DoneAction, ExtractContentAction
from pirlo.infrastructure.adapters.browser.content_sanitizer import (
    PageContentSanitizer,
)
from pirlo.infrastructure.adapters.browser.playwright_adapter import PlaywrightAdapter


class TestPageContentSanitizer(unittest.IsolatedAsyncioTestCase):
    async def test_prune_dom_noise(self):
        page = MagicMock()
        page.evaluate = AsyncMock()

        sanitizer = PageContentSanitizer(noise_selectors=("nav", "footer"))
        await sanitizer.prune_dom_noise(page)

        page.evaluate.assert_called_once()

    async def test_extract_markdown_main_locator_priority(self):
        page = MagicMock()
        page.evaluate = AsyncMock()

        main_locator = MagicMock()
        main_locator.count = AsyncMock(return_value=1)
        main_locator.inner_html = AsyncMock(
            return_value="<h1>Main Title</h1><p>Main content paragraph.</p>"
        )

        page.locator.return_value.first = main_locator

        sanitizer = PageContentSanitizer()
        result = await sanitizer.extract_markdown(page)

        self.assertIn("Main Title", result)
        self.assertIn("Main content paragraph.", result)


class TestPlaywrightAdapterExtraction(unittest.IsolatedAsyncioTestCase):
    async def test_extract_content_action_delegates_to_sanitizer(self):
        page = MagicMock()
        page_waiter = MagicMock()
        page_waiter.wait_for_text_settled = AsyncMock()

        sanitizer = MagicMock()
        sanitizer.extract_markdown = AsyncMock(return_value="Extracted Markdown")

        adapter = PlaywrightAdapter(
            page=page, page_waiter=page_waiter, content_sanitizer=sanitizer
        )
        action = ExtractContentAction()

        await adapter.execute_action(action)

        page_waiter.wait_for_text_settled.assert_called_once()
        sanitizer.extract_markdown.assert_called_once_with(page)
        self.assertEqual(adapter.last_extraction_result, "Extracted Markdown")

    async def test_done_action_uses_last_extraction_result_if_available(self):
        page = MagicMock()
        page_waiter = MagicMock()
        sanitizer = MagicMock()

        adapter = PlaywrightAdapter(
            page=page, page_waiter=page_waiter, content_sanitizer=sanitizer
        )
        adapter.last_extraction_result = "Previously Extracted Text"

        action = DoneAction(text="")
        await adapter.execute_action(action)

        self.assertEqual(action.text, "Previously Extracted Text")
        sanitizer.extract_markdown.assert_not_called()

    async def test_done_action_captures_markdown_if_no_prior_extraction(self):
        page = MagicMock()
        page_waiter = MagicMock()
        page_waiter.wait_for_text_settled = AsyncMock()

        sanitizer = MagicMock()
        sanitizer.extract_markdown = AsyncMock(return_value="Final Markdown Text")

        adapter = PlaywrightAdapter(
            page=page, page_waiter=page_waiter, content_sanitizer=sanitizer
        )
        adapter.last_extraction_result = None

        action = DoneAction(text="")
        await adapter.execute_action(action)

        page_waiter.wait_for_text_settled.assert_called_once()
        sanitizer.extract_markdown.assert_called_once_with(page)
        self.assertEqual(action.text, "Final Markdown Text")
