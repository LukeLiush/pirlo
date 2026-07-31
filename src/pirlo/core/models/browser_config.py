from pydantic import BaseModel


class BrowserConfig(BaseModel):
    cdp_url: str | None = None
    headless: bool = True
