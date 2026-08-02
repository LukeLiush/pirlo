import unittest
from unittest.mock import AsyncMock, MagicMock

from pirlo.core.models.actions import ElementContext
from pirlo.infrastructure.adapters.browser.locator_resolver import (
    ResilientLocatorResolver,
)


class TestResilientLocatorResolver(unittest.IsolatedAsyncioTestCase):
    async def test_primary_xpath_succeeds(self):
        page = MagicMock()
        primary_locator = MagicMock()
        primary_locator.wait_for = AsyncMock()
        page.locator.return_value.first = primary_locator

        resolver = ResilientLocatorResolver(page, timeout_ms=3000)
        context = ElementContext(
            xpath="/html/body/div[1]/a",
            tag_name="a",
            text="Gemini",
            attributes={"href": "https://gemini.google.com"},
        )

        resolved = await resolver.resolve(context)
        self.assertEqual(resolved, primary_locator)
        page.locator.assert_called_with("xpath=/html/body/div[1]/a")

    async def test_fallback_to_text_when_xpath_times_out(self):
        page = MagicMock()
        primary_locator = MagicMock()
        primary_locator.wait_for = AsyncMock(side_effect=TimeoutError("XPath timeout"))
        page.locator.return_value.first = primary_locator

        text_locator = MagicMock()
        text_locator.count = AsyncMock(return_value=1)
        page.get_by_text.return_value.first = text_locator

        resolver = ResilientLocatorResolver(page, timeout_ms=3000)
        context = ElementContext(
            xpath="/broken/xpath",
            tag_name="a",
            text="Access Gemini",
            attributes={},
        )

        resolved = await resolver.resolve(context)
        self.assertEqual(resolved, text_locator)
        page.get_by_text.assert_called_with("Access Gemini", exact=False)

    async def test_fallback_to_attribute_when_xpath_and_text_fail(self):
        page = MagicMock()
        primary_locator = MagicMock()
        primary_locator.wait_for = AsyncMock(side_effect=TimeoutError("XPath timeout"))

        # Primary locator and attribute locator mock routing
        attr_locator = MagicMock()
        attr_locator.count = AsyncMock(return_value=1)

        def mock_locator(selector):
            mock_obj = MagicMock()
            if "href" in selector:
                mock_obj.first = attr_locator
            else:
                mock_obj.first = primary_locator
            return mock_obj

        page.locator.side_effect = mock_locator

        # Text search returns 0 matches
        no_text_loc = MagicMock()
        no_text_loc.count = AsyncMock(return_value=0)
        page.get_by_text.return_value.first = no_text_loc

        resolver = ResilientLocatorResolver(page, timeout_ms=3000)
        context = ElementContext(
            xpath="/broken/xpath",
            tag_name="a",
            text="Changed Text",
            attributes={"href": "https://gemini.google.com"},
        )

        resolved = await resolver.resolve(context)
        self.assertEqual(resolved, attr_locator)


if __name__ == "__main__":
    unittest.main()
