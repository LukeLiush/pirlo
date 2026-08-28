from pirlo.core.models.link import LinkTestResult, LlmLink
from pirlo.infrastructure.services.llm_client import LlmClient


class LinkTester:
    @staticmethod
    def test_link(link: LlmLink) -> LinkTestResult:
        """Tests provider support, credentials, and connectivity of a link via LiteLLM."""
        try:
            response = LlmClient.completion(
                link=link,
                prompt="respond with 'OK'",
                temperature=0.0,
                max_tokens=100,
                timeout=10.0,
            )
            if response:
                return LinkTestResult(success=True, message="Connection successful!")
            return LinkTestResult(
                success=False, message="No response received from LLM provider."
            )
        except Exception as e:  # noqa: BLE001
            return LinkTestResult(success=False, message=f"Connection failed: {e!s}")
