from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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
    for pattern in (
        r"(?:oddscomp|h2h|analysis|live|tips|match|detail)[^0-9]*(\\d{5,})",
        r"/(\d{6,})(?:[/?#]|$)",
    ):
        m = re.search(pattern, href or "", re.I)
        if m:
            return m.group(1)
    return None

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
            elif full_year == "day":
                d,h,mi=vals
                mo=datetime.now().month
                y=year
            elif full_year == "month":
                d,month,h,mi=vals
                mo=month
                y=year
            else:
                mo,d,h,mi=vals
                y=year
            try:
                return datetime(y,mo,d,h,mi)
            except ValueError:
                pass
    return None

def _status(text: str, home: int | None, away: int | None, kickoff: datetime | None = None) -> str:
    low=text.lower()
    if re.search(r"\b(live|in[- ]play|1h|2h|ht|half time|\d{1,3}\s*')\b", low):
        return "live"
    if home is not None and away is not None:
        return "finished"
    if kickoff is not None:
        now = datetime.now()
        if kickoff <= now <= kickoff + timedelta(minutes=135):
            return "live"
    return "scheduled"

class GoalooParser:
    def parse_schedule_html(self, html: str, base_url: str | None = None) -> list[MatchRow]:
        soup = BeautifulSoup(html, "lxml")
        found: dict[str, MatchRow] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            mid = _match_id_from_href(href)
            if not mid:
                continue
            container = a.find_parent("tr")
            if container is None:
                container = a
                for _ in range(8):
                    parent = container.parent
                    if parent is None:
                        break
                    if len(parent.find_all("a", href=True)) >= 3:
                        container = parent
                        break
                    container = parent
            text = container.get_text(" | ", strip=True)
            links = container.find_all("a", href=True)
            names = []
            for link in links:
                name = link.get_text(" ", strip=True)
                if not name or name.lower() in {"analysis", "odds", "h2h", "tips", "detail", "live"}:
                    continue
                if link is not a and _match_id_from_href(link.get("href", "")):
                    continue
                names.append(name)
            names = list(dict.fromkeys(names))
            if len(names) < 2:
                continue
            pairs = re.findall(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)", text)
            home = away = None
            if pairs:
                home, away = map(int, pairs[0])
            kickoff = _kickoff(text)
            found[mid] = MatchRow(
                mid, None, names[0], names[1], home, away,
                source_url=urljoin(base_url, href) if base_url else href,
                kickoff_at=kickoff,
                status=_status(text, home, away, kickoff),
            )
        return list(found.values())

    def parse_schedule_payloads(self, payloads: list[dict] | None, base_url: str | None = None) -> list[MatchRow]:
        found = {}
        if not payloads:
            return []
        status_map = {0:"scheduled",1:"live",2:"live",3:"live",4:"live",5:"live",-1:"finished",-10:"cancelled",-11:"scheduled",-12:"finished",-13:"live",-14:"scheduled"}
        def walk(obj):
            if isinstance(obj, dict):
                mid = obj.get("matchId") or obj.get("matchID")
                home = obj.get("homeName") or obj.get("homeTeamName")
                away = obj.get("awayName") or obj.get("awayTeamName")
                if mid is not None and home and away:
                    yield obj
                for value in obj.values():
                    yield from walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    yield from walk(value)
        for payload in payloads:
            for obj in walk(payload):
                mid = str(obj.get("matchId") or obj.get("matchID"))
                if not mid.isdigit() or mid in found:
                    continue
                try:
                    status = status_map.get(int(obj.get("status")), "scheduled")
                except (TypeError, ValueError):
                    status = str(obj.get("status") or "scheduled").lower()
                ts = obj.get("matchTime")
                kickoff = None
                if ts:
                    try:
                        value = int(ts)
                        kickoff = datetime.fromtimestamp(value / 1000 if value > 10000000000 else value)
                    except (TypeError, ValueError, OSError):
                        pass
                def to_int(value):
                    try:
                        return int(value) if value is not None else None
                    except (TypeError, ValueError):
                        return None
                found[mid] = MatchRow(mid, None, str(obj.get("homeName") or obj.get("homeTeamName")), str(obj.get("awayName") or obj.get("awayTeamName")), to_int(obj.get("homeScore")), to_int(obj.get("awayScore")), to_int(obj.get("homeHalfScore")), to_int(obj.get("awayHalfScore")), source_url=f"{base_url.rstrip('/')}/football/match/live-{mid}" if base_url else None, kickoff_at=kickoff, status=status)
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
