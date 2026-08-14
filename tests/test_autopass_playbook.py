import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from pirlo.playbooks.autopass.main import QuickProgressListener, AutopassSession
from pirlo.playbooks.autopass.core.use_cases import slugify, RunAutopassUseCase


def test_quick_progress_listener_status_context():
    listener = QuickProgressListener()
    # Ensure status_context works as a context manager without raising AttributeError
    with listener.status_context("Testing status context..."):
        assert True
    # Test show methods
    listener.show_warning("Test warning")
    listener.show_goal("Test goal", detail="Detail goal")
    listener.show_red_card("Test red card", detail="Detail error")


def test_slugify_task_prompt():
    assert slugify("Go to google.com and search for OpenAI!") == "go_to_googlecom_and_search_for_openai"
    assert slugify("   Navigate to github.com / trending   ") == "navigate_to_githubcom_trending"


@pytest.mark.anyio
async def test_run_autopass_use_case_cache_key():
    mock_browser_manager = MagicMock()
    mock_browser_manager.launch = AsyncMock()
    mock_browser_manager.close = AsyncMock()

    mock_cdp_checker = MagicMock()
    mock_cdp_checker.wait_until_ready = AsyncMock()

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(side_effect=lambda task_prompt, cache_key, run_id: f"result_for_{cache_key}")

    use_case = RunAutopassUseCase(
        browser_manager=mock_browser_manager,
        cdp_checker=mock_cdp_checker,
        workflow_runner=mock_runner,
    )

    listener = QuickProgressListener()
    res = await use_case.run(
        task_prompt="Search OpenAI on Google",
        profile_path=Path("/tmp/test_profile"),
        headless=True,
        cdp_port=9222,
        listener=listener,
        run_name="run123",
        run_id="id123",
    )

    assert res == "result_for_run123_search_openai_on_google"
