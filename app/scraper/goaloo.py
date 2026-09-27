from dataclasses import dataclass
from urllib.parse import urljoin
from app.config import settings
from app.scraper.client import GoalooBrowser

@dataclass(slots=True)
class RawPage:
    url: str
    html: str

class GoalooScraper:
    def __init__(self) -> None:
        self.browser = GoalooBrowser()

    async def close(self) -> None:
        await self.browser.close()

    async def _fetch(self, url: str) -> RawPage:
        await self.browser.start()
        async with self.browser.page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.scraper_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)
            return RawPage(url=url, html=await page.content())

    async def fetch_schedule(self, round_no: int | None = None) -> RawPage:
        url = urljoin(settings.goaloo_base_url, settings.goaloo_league_path)
        if round_no is not None:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}round={round_no}"
        return await self._fetch(url)

    async def fetch_live_fixtures(self) -> RawPage:
        url = urljoin(settings.goaloo_base_url, settings.goaloo_live_path)
        return await self._fetch(url)

    async def fetch_match(self, url: str) -> RawPage:
        return await self._fetch(url)
