from dataclasses import dataclass
import json
from urllib.parse import urljoin
from app.config import settings
from app.scraper.client import GoalooBrowser

@dataclass(slots=True)
class RawPage:
    url: str
    html: str
    payloads: list[dict] | None = None
    response_meta: list[dict] | None = None

class GoalooScraper:
    def __init__(self) -> None:
        self.browser = GoalooBrowser()

    async def close(self) -> None:
        await self.browser.close()

    async def _fetch(self, url: str) -> RawPage:
        await self.browser.start()
        async with self.browser.page() as page:
            responses = []

            def capture(response):
                u = response.url.lower()
                if any(token in u for token in ("goaloo", "isportsapi", "/api/", "livescore", "football")):
                    responses.append(response)

            page.on("response", capture)
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.scraper_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(4_000)

            payloads = []
            response_meta = []
            for response in responses[-160:]:
                try:
                    body = await response.body()
                    response_meta.append({
                        "url": response.url,
                        "status": response.status,
                        "content_type": response.headers.get("content-type"),
                        "bytes": len(body),
                    })
                    if len(body) > 2_000_000:
                        continue
                    payloads.append(json.loads(body.decode("utf-8", errors="ignore")))
                except Exception as exc:
                    response_meta.append({
                        "url": response.url,
                        "status": response.status,
                        "content_type": response.headers.get("content-type"),
                        "error": type(exc).__name__,
                    })

            return RawPage(
                url=url,
                html=await page.content(),
                payloads=payloads,
                response_meta=response_meta,
            )

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
