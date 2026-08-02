import json
import os
import tempfile
import unittest
from pathlib import Path

from pirlo.core.models.link import ApiKeyLink
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
        link = ApiKeyLink(
            name="test-gemini",
            provider="gemini",
            model="gemini-1.5-flash",
            api_key="key123",
            base_url="https://gemini.url"
        )
        
        # 1. Save
        self.repo.save(link)
        
        # 2. Get by name
        fetched = self.repo.get_by_name("test-gemini")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "test-gemini")
        self.assertEqual(fetched.provider, "gemini")
        self.assertEqual(fetched.model, "gemini-1.5-flash")
        self.assertTrue(isinstance(fetched, ApiKeyLink))
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

    def test_llm_factory_registry_resolution(self):
        """Verify LlmFactory creates correct LangChain LLMs for ApiKeyLink, BedrockLink, and AzureOpenAiLink."""
        from pirlo.core.models.link import ApiKeyLink, AzureOpenAiLink, BedrockLink
        from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory

        # 1. ApiKeyLink
        api_link = ApiKeyLink(
            name="openai-test",
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
        llm = LlmFactory.create_langchain_llm(api_link)
        self.assertEqual(getattr(llm, "provider"), "openai")
        self.assertEqual(getattr(llm, "model"), "gpt-4o-mini")

        # 2. BedrockLink
        bedrock_link = BedrockLink(
            name="bedrock-test",
            provider="bedrock",
            model="anthropic.claude-3-5-sonnet",
            aws_access_key_id="key123",
            aws_secret_access_key="sec123",
            aws_region="us-east-1",
        )
        from unittest.mock import MagicMock, patch
        mock_bedrock = MagicMock()
        with patch.dict("sys.modules", {"langchain_aws": mock_bedrock}):
            mock_bedrock.ChatBedrockConverse = MagicMock(return_value=MagicMock(provider="bedrock", model="anthropic.claude-3-5-sonnet"))
            bedrock_llm = LlmFactory.create_langchain_llm(bedrock_link)
            self.assertEqual(getattr(bedrock_llm, "provider"), "bedrock")
            self.assertEqual(getattr(bedrock_llm, "model"), "anthropic.claude-3-5-sonnet")

        # 3. AzureOpenAiLink
        azure_link = AzureOpenAiLink(
            name="azure-test",
            provider="azure",
            model="gpt-4o",
            api_key="az-key",
            azure_endpoint="https://test.openai.azure.com",
            api_version="2024-02-15",
        )
        azure_llm = LlmFactory.create_langchain_llm(azure_link)
        self.assertEqual(getattr(azure_llm, "provider"), "azure")
        self.assertEqual(getattr(azure_llm, "model"), "gpt-4o")


    def test_link_display_fields(self):
        """Verify get_display_fields returns correctly formatted and masked details for all subclasses."""
        from pirlo.core.models.link import ApiKeyLink, AzureOpenAiLink, BedrockLink
        
        # 1. ApiKeyLink
        apilink = ApiKeyLink(
            name="my-gemini",
            provider="gemini",
            model="gemini-1.5-flash",
            api_key="123456789abcdef",
            base_url="https://gemini.url"
        )
        fields = dict(apilink.get_display_fields())
        self.assertEqual(fields["Model"], "gemini-1.5-flash")
        self.assertEqual(fields["API Key"], "1234...cdef")
        self.assertEqual(fields["Base URL"], "https://gemini.url")

        # 2. BedrockLink
        bedrock = BedrockLink(
            name="my-bedrock",
            provider="bedrock",
            model="anthropic.claude-v3",
            aws_access_key_id="access123",
            aws_secret_access_key="secret456789abc",
            aws_region="us-east-1"
        )
        fields = dict(bedrock.get_display_fields())
        self.assertEqual(fields["Model"], "anthropic.claude-v3")
        self.assertEqual(fields["Access Key ID"], "access123")
        self.assertEqual(fields["Secret Access Key"], "secr...9abc")
        self.assertEqual(fields["Region"], "us-east-1")

        # 3. AzureOpenAiLink
        azure = AzureOpenAiLink(
            name="my-azure",
            provider="azure",
            model="gpt-4",
            api_key="key78910abcdef",
            azure_endpoint="https://myazure.openai.azure.com",
            api_version="2024-02-15"
        )
        fields = dict(azure.get_display_fields())
        self.assertEqual(fields["Model"], "gpt-4")
        self.assertEqual(fields["API Key"], "key7...cdef")
        self.assertEqual(fields["Endpoint"], "https://myazure.openai.azure.com")
        self.assertEqual(fields["API Version"], "2024-02-15")

        # 4. Short key masking logic fallback
        short_apilink = ApiKeyLink(
            name="my-gemini-short",
            provider="gemini",
            model="gemini-1.5-flash",
            api_key="abc",
        )
        fields_short = dict(short_apilink.get_display_fields())
        self.assertEqual(fields_short["API Key"], "...")


if __name__ == "__main__":
    unittest.main()
