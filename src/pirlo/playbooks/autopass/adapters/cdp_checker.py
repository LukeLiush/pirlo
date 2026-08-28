import asyncio
import logging
import urllib.request

from pirlo.playbooks.autopass.core.ports import CdpChecker

logger = logging.getLogger("autopass.cdp")


class HttpCdpConnectionChecker(CdpChecker):
    """Adapter implementing CdpChecker via HTTP requests to the CDP version endpoint."""

    def __init__(self, cdp_url: str) -> None:
        self.cdp_url: str = cdp_url

    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        logger.info("Waiting for CDP endpoint at %s ...", self.cdp_url)
        deadline = asyncio.get_running_loop().time() + timeout
        last_err = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                loop = asyncio.get_running_loop()

                def check() -> bool:
                    with urllib.request.urlopen(
                        f"{self.cdp_url}/json/version", timeout=2
                    ) as resp:
                        return resp.status == 200

                is_live = await loop.run_in_executor(None, check)
                if is_live:
                    logger.info("CDP endpoint is live.")
                    return
            except Exception as e:  # noqa: BLE001
                last_err = e
                await asyncio.sleep(0.5)
        raise RuntimeError(
            f"CDP endpoint {self.cdp_url} never became ready. Last error: {last_err}"
        )
