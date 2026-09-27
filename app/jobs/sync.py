import asyncio
import argparse
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Bookmaker, Country, League, Match, OddsSnapshot, Season, ScrapeRun, Team
from app.scraper.goaloo import GoalooScraper
from app.scraper.parsers.goaloo import GoalooParser


def get_or_create(session: Session, model, defaults=None, **lookup):
    obj = session.scalar(select(model).filter_by(**lookup))
    if obj is None:
        obj = model(**lookup, **(defaults or {}))
        session.add(obj)
        session.flush()
    return obj


def save_match(session: Session, row, season: Season) -> Match:
    match = session.scalar(select(Match).where(Match.goaloo_id == row.goaloo_id))
    home = get_or_create(session, Team, name=row.home_team)
    away = get_or_create(session, Team, name=row.away_team)
    if match is None:
        match = Match(goaloo_id=row.goaloo_id, season_id=season.id, home_team_id=home.id, away_team_id=away.id)
        session.add(match)
    match.source_url = row.source_url
    match.season_id = season.id
    match.round = row.round
    match.home_team_id = home.id
    match.away_team_id = away.id
    match.home_score = row.home_score
    match.away_score = row.away_score
    match.home_ht_score = row.home_ht_score
    match.away_ht_score = row.away_ht_score
    match.status = "finished" if row.home_score is not None and row.away_score is not None else "scheduled"
    session.flush()
    return match


def save_odds(session: Session, match: Match, rows) -> int:
    saved = 0
    for row in rows:
        bookmaker = get_or_create(session, Bookmaker, name=row.bookmaker)
        session.add(OddsSnapshot(
            match_id=match.id, bookmaker_id=bookmaker.id, market=row.market,
            phase=row.phase, odds_format="decimal", home_odds=row.home_odds,
            line=row.line, away_odds=row.away_odds, draw_odds=row.draw_odds,
            captured_at=row.captured_at, source_label=row.source_label,
            raw_payload=row.raw_payload,
        ))
        saved += 1
    return saved


async def run(rounds: list[int]) -> None:
    Base.metadata.create_all(bind=engine)
    scraper = GoalooScraper()
    parser = GoalooParser()
    run_row = ScrapeRun(job_name="goaloo_sync", status="running", started_at=datetime.now(timezone.utc))
    with SessionLocal() as session:
        session.add(run_row)
        session.commit()
    seen = saved = 0
    try:
        with SessionLocal() as session:
            country = get_or_create(session, Country, name="England")
            league = get_or_create(
                session, League, country_id=country.id, name="Premier League", goaloo_id="36",
                defaults={"source_url": settings.goaloo_base_url + settings.goaloo_league_path},
            )
            season = get_or_create(session, Season, league_id=league.id, name=settings.goaloo_season)
            session.commit()
            for round_no in rounds:
                raw = await scraper.fetch_schedule(round_no)
                matches = parser.parse_schedule_html(raw.html, base_url=raw.url)
                for row in matches:
                    row.round = round_no
                    seen += 1
                    match = save_match(session, row, season)
                    if row.source_url:
                        detail = await scraper.fetch_match(row.source_url)
                        saved += save_odds(session, match, parser.parse_analysis_html(detail.html))
                session.commit()
        with SessionLocal() as session:
            r = session.get(ScrapeRun, run_row.id)
            r.status = "success"
            r.finished_at = datetime.now(timezone.utc)
            r.items_seen = seen
            r.items_saved = saved
            session.commit()
    except Exception as exc:
        with SessionLocal() as session:
            r = session.get(ScrapeRun, run_row.id)
            r.status = "failed"
            r.finished_at = datetime.now(timezone.utc)
            r.items_seen = seen
            r.items_saved = saved
            r.error_text = repr(exc)
            session.commit()
        raise
    finally:
        await scraper.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", dest="rounds", type=int, action="append")
    args = ap.parse_args()
    asyncio.run(run(args.rounds or [settings.goaloo_round]))


if __name__ == "__main__":
    main()
