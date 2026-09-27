from pathlib import Path
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db, SessionLocal
from app import models

app = FastAPI(title="BetAppist API", version="0.2.0")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

NATIONAL_TEAMS = [
("Türkiye","TUR","UEFA"),("Almanya","GER","UEFA"),("İngiltere","ENG","UEFA"),("Fransa","FRA","UEFA"),("İspanya","ESP","UEFA"),
("İtalya","ITA","UEFA"),("Portekiz","POR","UEFA"),("Hollanda","NED","UEFA"),("Belçika","BEL","UEFA"),("Hırvatistan","CRO","UEFA"),
("İsviçre","SUI","UEFA"),("Avusturya","AUT","UEFA"),("Danimarka","DEN","UEFA"),("İskoçya","SCO","UEFA"),("Norveç","NOR","UEFA"),
("İsveç","SWE","UEFA"),("Polonya","POL","UEFA"),("Çekya","CZE","UEFA"),("Sırbistan","SRB","UEFA"),("Yunanistan","GRE","UEFA"),
("Brezilya","BRA","CONMEBOL"),("Arjantin","ARG","CONMEBOL"),("Uruguay","URU","CONMEBOL"),("Kolombiya","COL","CONMEBOL"),
("Şili","CHI","CONMEBOL"),("Ekvador","ECU","CONMEBOL"),("Peru","PER","CONMEBOL"),("Paraguay","PAR","CONMEBOL"),
("ABD","USA","CONCACAF"),("Meksika","MEX","CONCACAF"),("Kanada","CAN","CONCACAF"),("Japonya","JPN","AFC"),("Güney Kore","KOR","AFC"),
("İran","IRN","AFC"),("Suudi Arabistan","KSA","AFC"),("Avustralya","AUS","AFC"),("Fas","MAR","CAF"),("Mısır","EGY","CAF"),
("Senegal","SEN","CAF"),("Nijerya","NGA","CAF"),("Kamerun","CMR","CAF")
]

@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for country, code, conf in NATIONAL_TEAMS:
            if not db.scalar(select(models.NationalTeam).where(models.NationalTeam.code == code)):
                db.add(models.NationalTeam(country=country, code=code, confederation=conf))
        db.commit()

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(BASE_DIR / "templates" / "index.html")

@app.get("/health")
def health():
    return {"status":"ok","service":"betappist","time":datetime.now(timezone.utc).isoformat()}

def match_dict(db: Session, match: models.Match, home: models.Team, away: models.Team):
    odds_rows = db.execute(
        select(models.OddsSnapshot, models.Bookmaker.name)
        .join(models.Bookmaker, models.Bookmaker.id == models.OddsSnapshot.bookmaker_id)
        .where(models.OddsSnapshot.match_id == match.id)
        .order_by(models.OddsSnapshot.captured_at.desc())
        .limit(20)
    ).all()
    odds=[]
    seen=set()
    for row, bookmaker in odds_rows:
        key=(row.market,row.phase,bookmaker)
        if key in seen: continue
        seen.add(key)
        vals=[]
        if row.home_odds is not None: vals.append(("MS 1",float(row.home_odds)))
        if row.draw_odds is not None: vals.append(("MS X",float(row.draw_odds)))
        if row.away_odds is not None: vals.append(("MS 2",float(row.away_odds)))
        for label,value in vals:
            odds.append({"label":label,"value":value,"market":row.market,"bookmaker":bookmaker,"captured_at":row.captured_at.isoformat()})
    return {
        "id":match.id,"goaloo_id":match.goaloo_id,"home_team":home.name,"away_team":away.name,
        "kickoff_at":match.kickoff_at.isoformat() if match.kickoff_at else None,"round":match.round,
        "status":match.status,"home_score":match.home_score,"away_score":match.away_score,
        "home_ht_score":match.home_ht_score,"away_ht_score":match.away_ht_score,"odds":odds
    }

@app.get("/api/matches")
def matches(db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)):
    rows=db.execute(select(models.Match,models.Team).join(models.Team,models.Team.id==models.Match.home_team_id)
        .order_by(models.Match.kickoff_at.asc().nulls_last(),models.Match.id.desc()).limit(limit)).all()
    return [match_dict(db,m,h,db.get(models.Team,m.away_team_id)) for m,h in rows]

@app.get("/api/archive")
def archive(db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=1000)):
    rows=db.execute(select(models.Match,models.Team).join(models.Team,models.Team.id==models.Match.home_team_id)
        .where(models.Match.status=="finished")
        .order_by(models.Match.kickoff_at.desc().nulls_last(),models.Match.id.desc()).limit(limit)).all()
    return [match_dict(db,m,h,db.get(models.Team,m.away_team_id)) for m,h in rows]

@app.get("/api/national-teams")
def national_teams(db: Session = Depends(get_db)):
    rows=db.scalars(select(models.NationalTeam).where(models.NationalTeam.active.is_(True)).order_by(models.NationalTeam.country)).all()
    return [{"id":r.id,"country":r.country,"code":r.code,"confederation":r.confederation} for r in rows]

@app.get("/api/system")
def system(db: Session = Depends(get_db)):
    latest=db.scalar(select(models.ScrapeRun).order_by(models.ScrapeRun.id.desc()))
    return {
        "matches":db.scalar(select(func.count(models.Match.id))) or 0,
        "teams":db.scalar(select(func.count(models.Team.id))) or 0,
        "national_teams":db.scalar(select(func.count(models.NationalTeam.id))) or 0,
        "odds":db.scalar(select(func.count(models.OddsSnapshot.id))) or 0,
        "last_scrape": {"status":latest.status,"started_at":latest.started_at.isoformat(),"finished_at":latest.finished_at.isoformat() if latest.finished_at else None,"items_seen":latest.items_seen,"items_saved":latest.items_saved} if latest else None
    }

@app.get("/api/matches/{match_id}")
def match_detail(match_id:int, db:Session=Depends(get_db)):
    m=db.get(models.Match,match_id)
    if not m: return {"error":"match_not_found"}
    return match_dict(db,m,db.get(models.Team,m.home_team_id),db.get(models.Team,m.away_team_id))
