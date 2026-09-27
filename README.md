# BetAppist v0.2

Goaloo football data ingestion platform.

## Verified Goaloo structure

Goaloo exposes:
- league/season schedules with round selectors;
- match pages with Detail / Analysis / Odds tabs;
- odds comparison tables with bookmakers such as Bet365, Sbobet and Crown;
- odds phases labelled Initial, Live and In-Play.

The 2024-2025 English Premier League schedule is exposed by Goaloo at:
`https://football.goaloo.com/league/2024-2025/36`

A completed Bournemouth-Leicester 2024-2025 match is also exposed as an odds-comparison page with match ID `2591268`.

## Important

Goaloo's schedule and odds content is partly JavaScript-rendered. Search-engine snapshots confirm the table structure, but do not expose all numeric odds values. Therefore v0.2:
1. captures the rendered HTML with Playwright;
2. discovers match IDs/URLs;
3. preserves raw odds row text;
4. keeps the parser isolated so the final numeric selectors can be tightened against the live rendered DOM.

Do not treat `Live` as "closing" automatically. For historical data, `Initial` and the final pre-match/closing state need to be identified from the actual rendered row/change history.

## Run locally

```bash
cp .env.example .env
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload
```

Test selected rounds:

```bash
python -m app.jobs.sync --round 38
```

Test all rounds:

```bash
python -m app.jobs.sync
```

## Production shape

- Render Web Service: API
- Render Cron Job: daily sync
- Render Postgres: persistent data
- Historical backfill: one-off/manual job
- Daily sync: idempotent upsert + new odds snapshots

Render cron schedules are UTC.

## Data

The schema now keeps:
- country / league / season / round
- Goaloo match ID + source URL
- teams and FT/HT scores
- bookmaker
- market / phase
- odds values and line
- source label
- raw rendered payload
- scrape-run status

## Alternative API

Goaloo links to iSports API. Its current football historical-odds documentation exposes opening/current odds and bookmaker IDs, but the documented historical endpoint only supports back-checking within the previous month. That is useful for validation and daily updates, but it does not replace Goaloo page scraping for a 2024-onward historical backfill.
