"""The pipeline's steps as plain functions.

The Airflow DAG and the command line both call these, so each step behaves
identically wherever it runs. Steps communicate only through the landing
zone and the warehouse, never through return values, so any one of them
can be re-run on its own.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import date
from pathlib import Path

from congress_trades import raw, warehouse
from congress_trades.config import Settings
from congress_trades.extract import house, prices, reference, senate
from congress_trades.http_client import PoliteSession
from congress_trades.storage import get_store

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = PROJECT_ROOT / "dbt"


def _session(settings: Settings, delay: float | None = None) -> PoliteSession:
    return PoliteSession(
        settings.http_user_agent, settings.request_delay if delay is None else delay
    )


def filing_years(settings: Settings, run_date: date) -> list[int]:
    return list(range(settings.coverage_start_date.year, run_date.year + 1))


def extract_house(settings: Settings, run_date: date) -> dict:
    return house.extract(
        _session(settings), get_store(settings), filing_years(settings, run_date), run_date
    )


def extract_senate(settings: Settings, run_date: date) -> dict:
    return senate.extract(
        _session(settings), get_store(settings), settings.coverage_start_date, run_date
    )


def extract_reference(settings: Settings, run_date: date) -> dict:
    store, session = get_store(settings), _session(settings)
    reference.extract_legislators(session, store, run_date)
    snaps = reference.extract_membership_history(
        session, store, settings.coverage_start_date, run_date
    )
    reference.extract_sec_tickers(session, store, run_date)
    return {"membership_snapshots_fetched": snaps}


def extract_market(settings: Settings, run_date: date) -> dict:
    """SEC industry codes and prices for every ticker that appears in a trade."""
    store = get_store(settings)
    _, house_tx = raw.build_house(store, filing_years(settings, run_date))
    _, senate_tx = raw.build_senate(store)
    tickers = raw.traded_tickers(house_tx, senate_tx, settings.coverage_start_date)

    sec_key = reference.latest_run_key(store, "reference/sec/", "company_tickers.json")
    sec_map = reference.sec_ticker_map(store.read(sec_key)) if sec_key else {}
    ciks = {sec_map[t]["cik"] for t in tickers if t in sec_map}
    # SEC allows 10 requests a second; stay well under it.
    fetched = reference.extract_sec_companies(_session(settings, 0.15), store, ciks)
    price_stats = prices.extract(
        _session(settings, 0.3), store, tickers, settings.coverage_start_date
    )
    return {"tickers": len(tickers), "sec_matched": len(ciks), "sec_fetched": fetched} | price_stats


def load_raw(settings: Settings, run_date: date) -> dict:
    store = get_store(settings)
    house_filings, house_tx = raw.build_house(store, filing_years(settings, run_date))
    senate_reports, senate_tx = raw.build_senate(store)
    terms, committees = raw.build_legislators(store, settings.coverage_start_date)
    sec_tickers, sec_companies = raw.build_sec(store)
    tables = {
        "house_filings": house_filings,
        "house_transactions": house_tx,
        "senate_reports": senate_reports,
        "senate_transactions": senate_tx,
        "legislator_terms": terms,
        "committees": committees,
        "committee_membership": raw.build_membership(store),
        "sec_tickers": sec_tickers,
        "sec_companies": sec_companies,
        "prices": raw.build_prices(store),
    }
    return warehouse.load_tables(settings, tables)


def dbt_env(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DBT_PROFILES_DIR", str(DBT_DIR))
    env["DBT_TARGET"] = env.get("DBT_TARGET") or ("local" if settings.is_local else "bigquery")
    env["DUCKDB_PATH"] = str(settings.duckdb_path.resolve())
    env["COVERAGE_START"] = settings.coverage_start
    return env


def run_dbt(settings: Settings, *args: str) -> None:
    dbt = os.environ.get("DBT_BIN", "dbt")
    cmd = [dbt, *(args or ("build",)), "--project-dir", str(DBT_DIR)]
    log.info("running %s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=dbt_env(settings), cwd=DBT_DIR)


def export(settings: Settings, out: Path | None = None) -> dict:
    from congress_trades import export as export_mod

    return export_mod.write_dashboard(settings, out)


STEPS = {
    "extract-house": extract_house,
    "extract-senate": extract_senate,
    "extract-reference": extract_reference,
    "extract-market": extract_market,
    "load-raw": load_raw,
}
