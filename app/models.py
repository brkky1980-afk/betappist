from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class Country(Base):
    __tablename__ = "countries"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    goaloo_id: Mapped[str | None] = mapped_column(String(100), unique=True)

class League(Base):
    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    goaloo_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text)

class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("league_id", "name", name="uq_season_league_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    name: Mapped[str] = mapped_column(String(40), index=True)

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    goaloo_id: Mapped[str | None] = mapped_column(String(100), unique=True)

class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("goaloo_id", name="uq_match_goaloo_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    goaloo_id: Mapped[str] = mapped_column(String(100), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    round: Mapped[int | None] = mapped_column(Integer, index=True)
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    home_ht_score: Mapped[int | None] = mapped_column(Integer)
    away_ht_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(40))

class Bookmaker(Base):
    __tablename__ = "bookmakers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (UniqueConstraint("match_id", "bookmaker_id", "market", "phase", "captured_at", name="uq_odds_snapshot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), index=True)
    market: Mapped[str] = mapped_column(String(30), index=True)
    phase: Mapped[str] = mapped_column(String(30), index=True)
    odds_format: Mapped[str] = mapped_column(String(20), default="decimal")
    home_odds: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    line: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    away_odds: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    draw_odds: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    source_label: Mapped[str | None] = mapped_column(String(40))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_saved: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text)
