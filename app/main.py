import asyncio
import httpx
from pathlib import Path
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Query, Header, HTTPException
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
live_source: str | None = None
live_task: asyncio.Task | None = None
sync_task: asyncio.Task | None = None
sync_state = {"status": "idle", "error": None}

@app.on_event("startup")
async def startup() -> None:
    global live_task
    Base.metadata.create_all(bind=engine)
    live_task = asyncio.create_task(refresh_live_cache_loop())

async def refresh_live_cache_loop() -> None:
    global live_cache, live_cache_updated, live_cache_error, live_source_url, live_html_bytes, live_rows, live_source
    while True:
        scraper = GoalooScraper()
        try:
            raw = await scraper.fetch_live_fixtures()
            parser = GoalooParser()
            rows = parser.parse_legacy_schedule_payloads(raw.payloads, base_url=raw.url) or parser.parse_schedule_payloads(raw.payloads, base_url=raw.url)
            if not rows:
                rows = parser.parse_schedule_html(raw.html, base_url=raw.url)
            live_source_url = raw.url
            live_html_bytes = len(raw.html)
            live_source = "goaloo"
            if not rows:
                leagues = ("eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "tur.1", "uefa.champions")
                async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "BetAppist/1.0"}) as client:
                    for league in leagues:
                        try:
                            resp = await client.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard")
                            if resp.status_code == 200:
                                rows.extend(parser.parse_espn_payload(resp.json(), f"https://site.api.espn.com/{league}"))
                        except Exception:
                            continue
                live_source = "espn-fallback"
                live_source_url = "https://site.api.espn.com/apis/site/v2/sports/soccer/*/scoreboard"
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
        for label,value in (("MS 1",row.home_odds),("MS X",row.draw_odds),("MS 2",row.away_odds)):
            if value is not None:
                odds.append({"label":label,"value":float(value),"market":row.market,"bookmaker":bookmaker,"captured_at":row.captured_at.isoformat()})
    return {"id":match.id,"goaloo_id":match.goaloo_id,"home_team":home.name,"away_team":away.name,
            "kickoff_at":match.kickoff_at.isoformat() if match.kickoff_at else None,"round":match.round,
            "status":match.status,"home_score":match.home_score,"away_score":match.away_score,
            "home_ht_score":match.home_ht_score,"away_ht_score":match.away_ht_score,"odds":odds}

@app.post("/api/admin/sync/start")
async def start_sync(from_round: int = Query(1, ge=1, le=38), to_round: int = Query(1, ge=1, le=38)):
    global sync_task, sync_state
    if from_round > to_round:
        raise HTTPException(status_code=400, detail="from_round must be <= to_round")
    if sync_task and not sync_task.done():
        return {"status": "running", **sync_state}
    rounds = list(range(from_round, to_round + 1))
    async def worker():
        global sync_state, sync_task
        from app.jobs.sync import run as run_sync
        sync_state = {"status": "running", "from_round": from_round, "to_round": to_round, "error": None}
        try:
            await run_sync(rounds)
            sync_state["status"] = "success"
        except Exception as exc:
            sync_state["status"] = "failed"
            sync_state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            sync_task = None
    sync_task = asyncio.create_task(worker())
    return {"status": "started", "from_round": from_round, "to_round": to_round}

@app.get("/api/admin/sync/status")
async def sync_status():
    state = dict(sync_state)
    with SessionLocal() as session:
        latest = session.scalar(select(models.ScrapeRun).order_by(models.ScrapeRun.id.desc()))
        if latest:
            state["last_scrape"] = {
                "status": latest.status,
                "items_seen": latest.items_seen or 0,
                "items_saved": latest.items_saved or 0
            }
    return state

@app.get("/api/debug/goaloo")
async def debug_goaloo(
    season: str = Query("2024-2025"),
    league_id: str = Query("36"),
    round_no: int = Query(1, ge=1, le=60),
):
    url = f"https://football.goaloo.com/league/{season}/{league_id}?round={round_no}"
    scraper = GoalooScraper()
    try:
        raw = await scraper._fetch(url)
        parser = GoalooParser()
        payload_rows = parser.parse_legacy_schedule_payloads(raw.payloads, base_url=raw.url) or parser.parse_schedule_payloads(raw.payloads, base_url=raw.url)
        html_rows = parser.parse_schedule_html(raw.html, base_url=raw.url)
        rows = [row for row in payload_rows if row.round == round_no] if payload_rows else html_rows
        schedule_samples = []
        schedule_info = {}
        for payload in (raw.payloads or []):
            if isinstance(payload, dict) and "ScheduleList" in payload:
                value = payload.get("ScheduleList")
                schedule_info = {
                    "type": type(value).__name__,
                    "length": len(value) if hasattr(value, "__len__") else None,
                    "repr": repr(value)[:5000],
                }
                if isinstance(value, list):
                    schedule_samples = value[:5]
                elif isinstance(value, dict):
                    schedule_samples = [value]
                break
        payload_summaries = []
        for payload in (raw.payloads or []):
            if isinstance(payload, dict):
                payload_summaries.append({
                    "keys": list(payload.keys())[:40],
                    "match_like_keys": [k for k in payload.keys() if "match" in k.lower() or "fixture" in k.lower() or "team" in k.lower()][:30],
                })
            elif isinstance(payload, list):
                payload_summaries.append({"type":"list", "length":len(payload)})
            else:
                payload_summaries.append({"type":type(payload).__name__})
        return {
            "url": raw.url,
            "season": season,
            "league_id": league_id,
            "round": round_no,
            "html_bytes": len(raw.html),
            "payload_count": len(raw.payloads or []),
            "payload_rows": len(payload_rows),
            "round_rows": len([row for row in payload_rows if row.round == round_no]),
            "html_rows": len(html_rows),
            "response_count": len(raw.response_meta or []),
            "responses": (raw.response_meta or [])[-80:],
            "payload_summaries": payload_summaries,
            "schedule_sample": schedule_samples,
            "schedule_info": schedule_info,
            "rows": [
                {
                    "goaloo_id": row.goaloo_id,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                    "home_score": row.home_score,
                    "away_score": row.away_score,
                    "kickoff_at": row.kickoff_at.isoformat() if row.kickoff_at else None,
                    "status": row.status,
                    "source_url": row.source_url,
                }
                for row in rows[:100]
            ],
        }
    except Exception as exc:
        return {
            "url": url,
            "season": season,
            "league_id": league_id,
            "round": round_no,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        await scraper.close()

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
