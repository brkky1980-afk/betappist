from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401

app = FastAPI(title="BetAppist API", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/matches")
def matches(db: Session = Depends(SessionLocal)):
    rows = db.execute(
        select(
            models.Match,
            models.Team,
        )
        .join(models.Team, models.Team.id == models.Match.home_team_id)
        .order_by(models.Match.kickoff_at.asc().nulls_last(), models.Match.id.desc())
        .limit(100)
    ).all()

    result = []
    for match, home_team in rows:
        away = db.get(models.Team, match.away_team_id)
        result.append({
            "id": match.id,
            "goaloo_id": match.goaloo_id,
            "home_team": home_team.name,
            "away_team": away.name if away else "Unknown",
            "kickoff_at": match.kickoff_at.isoformat() if match.kickoff_at else None,
            "round": match.round,
            "status": match.status,
            "home_score": match.home_score,
            "away_score": match.away_score,
        })
    return result
