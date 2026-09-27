from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

@dataclass(slots=True)
class MatchRow:
    goaloo_id: str
    round: int | None
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    home_ht_score: int | None = None
    away_ht_score: int | None = None
    source_url: str | None = None
    kickoff_at: datetime | None = None
    status: str = "scheduled"

@dataclass(slots=True)
class OddsRow:
    bookmaker: str
    market: str
    phase: str
    home_odds: Decimal | None
    line: Decimal | None
    away_odds: Decimal | None
    draw_odds: Decimal | None
    captured_at: datetime
    source_label: str | None = None
    raw_payload: dict | None = None

BOOKMAKERS = {"Bet365", "Sbobet", "Crown", "Macauslot", "Ladbrokes", "Easybet", "Vcbet", "M88", "12BET", "18Bet", "Interwetten", "Bwin", "William Hill"}

def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None

def _match_id_from_href(href: str) -> str | None:
    m = re.search(r"(?:oddscomp|h2h|analysis|live|tips)-?(\d{5,})", href or "")
    return m.group(1) if m else None

def _kickoff(text: str) -> datetime | None:
    year = datetime.now().year
    patterns = [
        (r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2}):(\d{2})\b", True),
        (r"\b(\d{1,2})[-/.](\d{1,2})\s+(\d{1,2}):(\d{2})\b", False),
    ]
    for pattern, full_year in patterns:
        m = re.search(pattern, text)
        if m:
            vals=list(map(int,m.groups()))
            if full_year:
                y,mo,d,h,mi=vals
            else:
                mo,d,h,mi=vals
                y=year
            try:
                return datetime(y,mo,d,h,mi)
            except ValueError:
                pass
    return None

def _status(text: str, home: int | None, away: int | None) -> str:
    low=text.lower()
    if re.search(r"\b(live|in[- ]play|1h|2h|ht|half time|\d{1,3}\s*')\b", low):
        return "live"
    if home is not None and away is not None:
        return "finished"
    return "scheduled"

class GoalooParser:
    def parse_schedule_html(self, html: str, base_url: str | None = None) -> list[MatchRow]:
        soup = BeautifulSoup(html, "lxml")
        found: dict[str, MatchRow] = {}
        for a in soup.find_all("a", href=True):
            mid = _match_id_from_href(a["href"])
            if not mid:
                continue
            row = a.find_parent("tr")
            if not row:
                continue
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            text = " | ".join(cells)
            score_pairs = re.findall(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)", text)
            home = away = None
            if score_pairs:
                home, away = map(int, score_pairs[0])
            team_links = []
            for link in row.find_all("a", href=True):
                t = link.get_text(" ", strip=True)
                if t and t.lower() not in {"analysis", "odds", "h2h", "tips", "detail"}:
                    team_links.append(t)
            team_links = list(dict.fromkeys(team_links))
            if len(team_links) < 2:
                continue
            href = a["href"]
            source_url = urljoin(base_url, href) if base_url else href
            found[mid] = MatchRow(
                mid, None, team_links[0], team_links[1], home, away,
                source_url=source_url, kickoff_at=_kickoff(text), status=_status(text, home, away)
            )
        return list(found.values())

    def parse_analysis_html(self, html: str) -> list[OddsRow]:
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(timezone.utc)
        rows: list[OddsRow] = []
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            bookmaker = cells[0].get_text(" ", strip=True)
            if bookmaker not in BOOKMAKERS:
                continue
            raw = [c.get_text(" ", strip=True) for c in cells[1:]]
            whole = " | ".join(raw)
            numbers = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z])", whole)
            payload = {"cells": raw, "numbers": numbers, "text": whole}
            rows.append(OddsRow(bookmaker, "UNKNOWN", "initial", None, None, None, None, now, "Initial", payload))
        return rows
