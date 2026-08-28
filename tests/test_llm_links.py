import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)
from pirlo.infrastructure.services.link_tester import LinkTester
from pirlo.infrastructure.services.llm_client import LlmClient


class TestLlmLinks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.filepath = Path(self.temp_dir.name) / "links.json"
        self.repo = JsonLinkRepository(self.filepath)

        self.original_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        self.temp_dir.cleanup()

    def test_link_repository_operations(self):
        """Verify standard save, get, list, and delete operations of the repository."""
        link = LlmLink(
            name="test-gemini",
            provider="gemini",
            model="gemini-1.5-flash",
            api_key="key123",
            base_url="https://gemini.url",
        )

        # 1. Save
        self.repo.save(link)

        # 2. Get by name
        fetched = self.repo.get_by_name("test-gemini")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "test-gemini")
        self.assertEqual(fetched.provider, "gemini")
        self.assertEqual(fetched.model, "gemini-1.5-flash")
        self.assertEqual(fetched.api_key, "key123")
        self.assertEqual(fetched.base_url, "https://gemini.url")

        # 3. List all
        links = self.repo.list_all()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].name, "test-gemini")

        # 4. Delete
        success = self.repo.delete("test-gemini")
        self.assertTrue(success)
        self.assertIsNone(self.repo.get_by_name("test-gemini"))
        self.assertEqual(len(self.repo.list_all()), 0)

    @patch("litellm.completion")
    def test_llm_client_completion(self, mock_litellm_completion):
        """Verify LlmClient completion correctly passes parameters to litellm."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello world!"))]
        mock_litellm_completion.return_value = mock_response

        link = LlmLink(
            name="dashscope-test",
            provider="dashscope",
            model="qwen-max",
            api_key="sk-dashscope-key",
        )

        res = LlmClient.completion(link=link, prompt="Say hello")
        self.assertEqual(res, "Hello world!")

        mock_litellm_completion.assert_called_once_with(
            model="qwen-max",
            custom_llm_provider="dashscope",
            messages=[{"role": "user", "content": "Say hello"}],
            api_key="sk-dashscope-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0.0,
            max_tokens=None,
            timeout=30.0,
        )

    @patch("litellm.completion")
    def test_link_tester_success(self, mock_litellm_completion):
        """Verify LinkTester returns success on clean LiteLLM completion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="OK"))]
        mock_litellm_completion.return_value = mock_response

        link = LlmLink(
            name="openai-test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
        )

        result = LinkTester.test_link(link)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Connection successful!")

    @patch(
        "litellm.completion", side_effect=Exception("Provider 'invalid' not supported")
    )
    def test_link_tester_failure(self, mock_litellm_completion):
        """Verify LinkTester catches exceptions and returns failure result."""
        link = LlmLink(
            name="invalid-test",
            provider="invalid",
            model="some-model",
            api_key="key",
        )

        result = LinkTester.test_link(link)
        self.assertFalse(result.success)
        self.assertIn(
            "Connection failed: Provider 'invalid' not supported", result.message
        )


if __name__ == "__main__":
    unittest.main()
