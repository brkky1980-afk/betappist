import asyncio
from pathlib import Path
from app.scraper.goaloo import GoalooScraper

async def main() -> None:
    scraper = GoalooScraper()
    try:
        raw = await scraper.fetch_schedule()
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/goaloo_schedule.html").write_text(raw.html, encoding="utf-8")
        print(raw.url)
        print("saved artifacts/goaloo_schedule.html")
    finally:
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())
