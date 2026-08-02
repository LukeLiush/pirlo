import os
import tempfile
import unittest
from pathlib import Path

from pirlo.core.models.link import LlmLink
from pirlo.infrastructure.adapters.storage.json_link_repository import (
    JsonLinkRepository,
)


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

    def test_llm_factory_creation(self):
        """Verify LlmFactory creates correct LangChain LLM for LlmLink."""
        from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory

        api_link = LlmLink(
            name="openai-test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
        llm = LlmFactory.create_langchain_llm(api_link)
        self.assertEqual(llm.provider, "openai")
        self.assertEqual(llm.model, "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
