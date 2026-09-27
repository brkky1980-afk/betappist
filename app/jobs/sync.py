import asyncio
import argparse
from app.scraper.goaloo import GoalooScraper
from app.scraper.parsers.goaloo import GoalooParser

async def run(rounds: list[int]) -> None:
    scraper = GoalooScraper()
    parser = GoalooParser()
    try:
        for round_no in rounds:
            raw = await scraper.fetch_schedule(round_no)
            matches = parser.parse_schedule_html(raw.html, base_url=raw.url)
            print(f"round={round_no} url={raw.url} matches={len(matches)}")
            for m in matches:
                print(f"  {m.goaloo_id}: {m.home_team} - {m.away_team} {m.home_score}:{m.away_score} {m.source_url}")
                if m.source_url:
                    detail = await scraper.fetch_match(m.source_url)
                    odds = parser.parse_analysis_html(detail.html)
                    print(f"    odds_rows={len(odds)}")
    finally:
        await scraper.close()

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", dest="rounds", type=int, action="append")
    args = ap.parse_args()
    rounds = args.rounds or list(range(1, 39))
    asyncio.run(run(rounds))

if __name__ == "__main__":
    main()
