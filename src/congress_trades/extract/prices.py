"""Daily closing prices for every traded ticker and the SPY benchmark.

Prices come from Yahoo Finance's public chart endpoint (the same data the
yfinance library reads), requested directly so the pipeline adds no
dependency. Stooq, the other free option, now sits behind a browser
challenge that scripts should not try to get around.

Unlike filings, prices can be fetched again at any time, so each ticker's
file is overwritten when it is older than a day rather than versioned:
``prices/yahoo/{ticker}.json``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime

from congress_trades.http_client import PoliteSession
from congress_trades.storage import Store

log = logging.getLogger(__name__)

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
BENCHMARK = "SPY"
STALE_SECONDS = 20 * 3600


def price_key(ticker: str) -> str:
    return f"prices/yahoo/{ticker}.json"


def _is_fresh(store: Store, key: str) -> bool:
    if not store.exists(key):
        return False
    try:
        fetched = json.loads(store.read(key)).get("_fetched_at", 0)
    except ValueError:
        return False
    return time.time() - fetched < STALE_SECONDS


def fetch_ticker(session: PoliteSession, ticker: str, since: date) -> dict | None:
    start = int(datetime(since.year, since.month, since.day, tzinfo=UTC).timestamp())
    resp = session.get(
        CHART.format(ticker=ticker),
        params={
            "period1": start,
            "period2": int(time.time()),
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        },
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("chart", {}).get("result"):
        return None
    return payload


def parse_chart(payload: dict, ticker: str) -> list[dict]:
    """Flatten a chart payload into one row per trading day."""
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    offset = result.get("meta", {}).get("gmtoffset", 0)
    rows = []
    for i, ts in enumerate(stamps):
        close = (quote.get("close") or [None] * len(stamps))[i]
        adj_close = adj[i] if i < len(adj) else None
        if close is None and adj_close is None:
            continue
        day = datetime.fromtimestamp(ts + offset, tz=UTC).date()
        rows.append(
            {
                "ticker": ticker,
                "price_date": day.isoformat(),
                "close": close,
                "adj_close": adj_close if adj_close is not None else close,
            }
        )
    return rows


def extract(session: PoliteSession, store: Store, tickers: set[str], since: date) -> dict:
    stats = {"fresh": 0, "fetched": 0, "not_found": 0}
    for ticker in sorted(tickers | {BENCHMARK}):
        key = price_key(ticker)
        if _is_fresh(store, key):
            stats["fresh"] += 1
            continue
        try:
            payload = fetch_ticker(session, ticker, since)
        except Exception as err:  # one bad ticker must not fail the whole run
            log.warning("prices %s failed: %s", ticker, err)
            payload = None
        if payload is None:
            stats["not_found"] += 1
            payload = {"chart": {"result": None}, "_not_found": True}
        payload["_fetched_at"] = time.time()
        store.write(key, json.dumps(payload).encode(), "application/json")
        if not payload.get("_not_found"):
            stats["fetched"] += 1
    log.info("prices extract: %s", stats)
    return stats
