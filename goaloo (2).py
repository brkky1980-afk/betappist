from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
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

BOOKMAKERS = {"Bet365", "Sbobet", "Crown", "Macauslot", "Ladbrokes", "Easybet",
              "Vcbet", "M88", "12BET", "18Bet", "Interwetten", "Bwin", "William Hill"}

def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    value = value.strip().replace(",", ".")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None

def ints(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text)]

def _match_id_from_href(href: str) -> str | None:
    m = re.search(r"(?:oddscomp|h2h|analysis|live|tips)-?(\d{5,})", href or "")
    return m.group(1) if m else None

class GoalooParser:
    def parse_schedule_html(self, html: str, base_url: str | None = None) -> list[MatchRow]:
        soup = BeautifulSoup(html, "lxml")
        found: dict[str, MatchRow] = {}

        # Goaloo uses several match URL variants. Collect every unique match ID,
        # then infer team/score text from the nearest table/list row.
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

            # Remove obvious UI-only cells and try to locate score-like cells.
            text = " | ".join(cells)
            nums = ints(text)
            home = away = None
            score_pairs = re.findall(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)", text)
            if score_pairs:
                home, away = map(int, score_pairs[0])

            # Team names are more reliably found from links than from flattened text.
            team_links = []
            for link in row.find_all("a", href=True):
                t = link.get_text(" ", strip=True)
                if t and t.lower() not in {"analysis", "odds", "h2h", "tips", "detail"}:
                    team_links.append(t)
            team_links = list(dict.fromkeys(team_links))
            if len(team_links) < 2:
                continue

            found[mid] = MatchRow(
                goaloo_id=mid,
                round=None,
                home_team=team_links[0],
                away_team=team_links[1],
                home_score=home,
                away_score=away,
                source_url=(base_url.rstrip("/") + "/" + a["href"].lstrip("/")) if base_url and a["href"].startswith("/") else a["href"],
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
            phases = [p for p in ("Initial", "Live", "In-Play") if p.lower() in whole.lower()]

            # Preserve every numeric token and the rendered row text. The exact
            # Goaloo DOM differs between desktop/mobile and can be changed by JS.
            # This gives the ingestion layer a stable raw representation while
            # allowing a DOM-specific extractor to be tightened later.
            numbers = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z])", whole)
            payload = {"cells": raw, "numbers": numbers, "text": whole}

            for phase in phases or ["Initial"]:
                rows.append(OddsRow(
                    bookmaker=bookmaker,
                    market="UNKNOWN",
                    phase=phase.lower().replace("-", "_"),
                    home_odds=None,
                    line=None,
                    away_odds=None,
                    draw_odds=None,
                    captured_at=now,
                    source_label=phase,
                    raw_payload=payload,
                ))
        return rows
