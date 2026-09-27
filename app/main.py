import asyncio
from pathlib import Path
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session
from app.db import Base, engine, get_db, SessionLocal
from app import models
from app.config import settings
from app.scraper.goaloo import GoalooScraper
from app.scraper.parsers.goaloo import GoalooParser

app = FastAPI(title="BetAppist API", version="0.4.0")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

live_cache: list[dict] = []
live_cache_updated: str | None = None
live_cache_error: str | None = None
live_source_url: str | None = None
live_html_bytes: int = 0
live_rows: int = 0
live_task: asyncio.Task | None = None

@app.on_event("startup")
async def startup() -> None:
    global live_task
    Base.metadata.create_all(bind=engine)
    live_task = asyncio.create_task(refresh_live_cache_loop())

async def refresh_live_cache_loop() -> None:
    global live_cache, live_cache_updated, live_cache_error, live_source_url, live_html_bytes, live_rows
    while True:
        scraper = GoalooScraper()
        try:
            raw = await scraper.fetch_live_fixtures()
            rows = GoalooParser().parse_schedule_html(raw.html, base_url=raw.url)
            live_source_url = raw.url
            live_html_bytes = len(raw.html)
            live_rows = len(rows)
            live_cache_error = None
            live_cache = [
                {
                    "id": -abs(hash(row.goaloo_id)) % 2_000_000_000,
                    "goaloo_id": row.goaloo_id,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                    "kickoff_at": row.kickoff_at.isoformat() if row.kickoff_at else None,
                    "round": row.round,
                    "status": row.status,
                    "home_score": row.home_score,
                    "away_score": row.away_score,
                    "home_ht_score": row.home_ht_score,
                    "away_ht_score": row.away_ht_score,
                    "odds": [],
                }
                for row in rows
            ]
            live_cache_updated = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            live_cache_error = f"{type(exc).__name__}: {exc}"
        
        finally:
            await scraper.close()
        await asyncio.sleep(60)

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(BASE_DIR / "templates" / "index.html")

@app.get("/health")
def health():
    return {"status":"ok","service":"betappist","time":datetime.now(timezone.utc).isoformat(),
            "live_cache":len(live_cache),"live_cache_updated":live_cache_updated,
            "live_cache_error":live_cache_error,"live_source_url":live_source_url,
            "live_html_bytes":live_html_bytes,"live_rows":live_rows}

def match_dict(db: Session, match: models.Match, home: models.Team, away: models.Team):
    odds_rows = db.execute(
        select(models.OddsSnapshot, models.Bookmaker.name)
        .join(models.Bookmaker, models.Bookmaker.id == models.OddsSnapshot.bookmaker_id)
        .where(models.OddsSnapshot.match_id == match.id)
        .order_by(models.OddsSnapshot.captured_at.desc()).limit(20)
    ).all()
    odds=[]; seen=set()
    for row, bookmaker in odds_rows:
        key=(row.market,row.phase,bookmaker)
        if key in seen: continue
        seen.add(key)
        for label,value in ((("MS 1",row.home_odds),("MS X",row.draw_odds),("MS 2",row.away_odds))):
            if value is not None:
                odds.append({"label":label,"value":float(value),"market":row.market,"bookmaker":bookmaker,"captured_at":row.captured_at.isoformat()})
    return {"id":match.id,"goaloo_id":match.goaloo_id,"home_team":home.name,"away_team":away.name,
            "kickoff_at":match.kickoff_at.isoformat() if match.kickoff_at else None,"round":match.round,
            "status":match.status,"home_score":match.home_score,"away_score":match.away_score,
            "home_ht_score":match.home_ht_score,"away_ht_score":match.away_ht_score,"odds":odds}

@app.get("/api/matches")
def matches(db: Session = Depends(get_db), limit: int = Query(300, ge=1, le=500)):
    live_first = case((models.Match.status == "live", 0), (models.Match.status == "scheduled", 1), else_=2)
    rows=db.execute(select(models.Match,models.Team).join(models.Team,models.Team.id==models.Match.home_team_id)
        .order_by(live_first, models.Match.kickoff_at.asc().nulls_last(), models.Match.id.desc()).limit(limit)).all()
    db_rows=[match_dict(db,m,h,db.get(models.Team,m.away_team_id)) for m,h in rows]
    merged={m["goaloo_id"]:m for m in db_rows}
    for m in live_cache:
        merged[m["goaloo_id"]]=m
    result=list(merged.values())
    result.sort(key=lambda m:(0 if m["status"]=="live" else 1 if m["status"]=="scheduled" else 2, m["kickoff_at"] or "9999"))
    return result[:limit]

@app.get("/api/archive")
def archive(db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=1000)):
    rows=db.execute(select(models.Match,models.Team).join(models.Team,models.Team.id==models.Match.home_team_id)
        .where(models.Match.status=="finished")
        .order_by(models.Match.kickoff_at.desc().nulls_last(),models.Match.id.desc()).limit(limit)).all()
    return [match_dict(db,m,h,db.get(models.Team,m.away_team_id)) for m,h in rows]

@app.get("/api/system")
def system(db: Session = Depends(get_db)):
    latest=db.scalar(select(models.ScrapeRun).order_by(models.ScrapeRun.id.desc()))
    return {"matches":db.scalar(select(func.count(models.Match.id))) or 0,"teams":db.scalar(select(func.count(models.Team.id))) or 0,
            "national_teams":db.scalar(select(func.count(models.NationalTeam.id))) or 0 if hasattr(models,"NationalTeam") else 0,
            "odds":db.scalar(select(func.count(models.OddsSnapshot.id))) or 0,
            "live_cache":len(live_cache),"live_cache_updated":live_cache_updated,
            "live_cache_error":live_cache_error,"live_source_url":live_source_url,
            "live_html_bytes":live_html_bytes,"live_rows":live_rows,
            "last_scrape":{"status":latest.status,"started_at":latest.started_at.isoformat(),"finished_at":latest.finished_at.isoformat() if latest.finished_at else None,
                           "items_seen":latest.items_seen,"items_saved":latest.items_saved} if latest else None}

@app.get("/api/matches/{match_id}")
def match_detail(match_id:int, db:Session=Depends(get_db)):
    m=db.get(models.Match,match_id)
    if not m: return {"error":"match_not_found"}
    return match_dict(db,m,db.get(models.Team,m.home_team_id),db.get(models.Team,m.away_team_id))
