from pirlo.core.models.link import LinkTestResult, LlmLink
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory


class LinkTester:
    @staticmethod
    def test_link(link: LlmLink) -> LinkTestResult:
        """Tests the connectivity of a link by sending a minimal token call."""
        try:
            llm = LlmFactory.create_langchain_llm(
                link=link,
                temperature=0.0,
                timeout=10.0,
            )
            # Try to invoke a simple message call
            llm.invoke("respond with 'OK'")
            return LinkTestResult(success=True, message="Connection successful!")
        except Exception as e:  # noqa: BLE001
            return LinkTestResult(success=False, message=f"Connection failed: {e!s}")
