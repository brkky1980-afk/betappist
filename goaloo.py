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

    async def fetch_schedule(self, round_no: int | None = None) -> RawPage:
        round_no = round_no or settings.goaloo_round
        url = urljoin(settings.goaloo_base_url, settings.goaloo_league_path)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}round={round_no}"
        await self.browser.start()
        async with self.browser.page() as page:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            return RawPage(url=url, html=await page.content())

    async def fetch_match(self, url: str) -> RawPage:
        if not self.browser._browser:
            await self.browser.start()
        async with self.browser.page() as page:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            return RawPage(url=url, html=await page.content())
