import unittest
from unittest.mock import AsyncMock, MagicMock

from pirlo.infrastructure.adapters.browser.page_waiter import ResilientPageWaiter


class TestResilientPageWaiter(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_load_succeeds(self):
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()

        waiter = ResilientPageWaiter(page)
        await waiter.wait_for_load(timeout_ms=3000)

        page.wait_for_load_state.assert_called_once_with(
            "domcontentloaded", timeout=3000
        )

    async def test_wait_for_load_handles_timeout(self):
        page = MagicMock()
        page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("Load timed out"))

        waiter = ResilientPageWaiter(page)
        # Should not raise exception
        await waiter.wait_for_load(timeout_ms=1000)

    async def test_wait_for_text_settled_stabilizes(self):
        page = MagicMock()
        body_locator = MagicMock()

        # Simulate text length growing then stabilizing: "Hel", "Hello", "Hello World", "Hello World"
        body_locator.inner_text = AsyncMock(
            side_effect=[
                "Hel",
                "Hello",
                "Hello World",
                "Hello World",
                "Hello World",
            ]
        )
        page.locator.return_value = body_locator

        waiter = ResilientPageWaiter(page)
        await waiter.wait_for_text_settled(
            max_wait_sec=5.0,
            check_interval_sec=0.01,
            required_stable_cycles=2,
        )

        # inner_text should be called until 2 consecutive cycles match
        self.assertGreaterEqual(body_locator.inner_text.call_count, 4)


if __name__ == "__main__":
    unittest.main()
