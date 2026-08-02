from pirlo.core.models.link import LlmLink, ApiKeyLink, LinkTestResult
from pirlo.playbooks.autopass.adapters.llm_factory import LlmFactory


class LinkTester:
    @staticmethod
    def test_link(link: LlmLink) -> LinkTestResult:
        """Tests the connectivity of a link by sending a minimal token call."""
        if not isinstance(link, ApiKeyLink):
            return LinkTestResult(success=False, message=f"Test connect not implemented for provider '{link.provider}'.")

        provider = link.provider.lower()
        model = link.model
        
        try:
            llm = LlmFactory.create_langchain_llm(
                provider=provider,
                model=model,
                api_key=link.api_key,
                base_url=link.base_url or "",
                temperature=0.0,
                timeout=10.0,
            )
            # Try to invoke a simple message call
            llm.invoke("respond with 'OK'")
            return LinkTestResult(success=True, message="Connection successful!")
        except Exception as e:
            return LinkTestResult(success=False, message=f"Connection failed: {str(e)}")

