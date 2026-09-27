import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator
from playwright.async_api import Browser, Page, Playwright, async_playwright
from app.config import settings

class GoalooBrowser:
    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._browser:
            return
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=settings.scraper_headless)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        if not self._browser:
            raise RuntimeError("Browser is not started")
        page = await self._browser.new_page()
        page.set_default_timeout(settings.scraper_timeout_ms)
        try:
            yield page
        finally:
            await page.close()
            await asyncio.sleep(settings.scraper_delay_ms / 1000)
