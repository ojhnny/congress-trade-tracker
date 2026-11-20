"""Turn landed source files into rows for the warehouse's `raw` dataset.

Raw rows keep source values as they were disclosed (dates stay strings,
amounts stay text) plus a pointer back to the landed file they came from.
All cleaning happens in dbt, so a cleaning bug never destroys information.

The raw tables are rebuilt in full from the landing zone on every run. That
keeps loading idempotent: re-running a day can't duplicate anything, and an
improved parser takes effect across all history on the next run. Parsed PDF
results are cached per parser version because PDF text extraction is the
one slow step.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import date

import yaml

from congress_trades.extract import house as house_x
from congress_trades.extract import prices as prices_x
from congress_trades.extract import reference as ref_x
from congress_trades.extract import senate as senate_x
from congress_trades.parse import house as house_p
from congress_trades.parse import senate as senate_p
from congress_trades.storage import Store

log = logging.getLogger(__name__)

HOUSE_PARSER_VERSION = 1

# name -> list of (column, type). Types are BigQuery names; DuckDB gets the
# equivalent. The same schema is enforced on both backends.
SCHEMAS: dict[str, list[tuple[str, str]]] = {
    "house_filings": [
        ("doc_id", "STRING"),
        ("year", "INT64"),
        ("prefix", "STRING"),
        ("first", "STRING"),
        ("last", "STRING"),
        ("suffix", "STRING"),
        ("state_district", "STRING"),
        ("filing_date", "STRING"),
        ("filing_type", "STRING"),
        ("pdf_url", "STRING"),
        ("landing_key", "STRING"),
        ("landed", "BOOL"),
        ("parse_status", "STRING"),
        ("parse_error", "STRING"),
        ("filer_name_on_report", "STRING"),
        ("n_transactions", "INT64"),
    ],
    "house_transactions": [
        ("doc_id", "STRING"),
        ("row_num", "INT64"),
        ("owner_code", "STRING"),
        ("asset_text", "STRING"),
        ("asset_name", "STRING"),
        ("ticker_raw", "STRING"),
        ("ticker", "STRING"),
        ("asset_type", "STRING"),
        ("transaction_type_raw", "STRING"),
        ("trade_date", "STRING"),
        ("notification_date", "STRING"),
        ("amount_raw", "STRING"),
        ("filing_status", "STRING"),
        ("description", "STRING"),
        ("subholding_of", "STRING"),
        ("comment", "STRING"),
        ("landing_key", "STRING"),
    ],
    "senate_reports": [
        ("report_id", "STRING"),
        ("kind", "STRING"),
        ("first", "STRING"),
        ("last", "STRING"),
        ("office", "STRING"),
        ("title", "STRING"),
        ("filing_date", "STRING"),
        ("url", "STRING"),
        ("landing_key", "STRING"),
        ("is_amendment", "BOOL"),
        ("landed", "BOOL"),
        ("parse_status", "STRING"),
        ("filed_date_on_report", "STRING"),
        ("n_transactions", "INT64"),
    ],
    "senate_transactions": [
        ("report_id", "STRING"),
        ("row_num", "INT64"),
        ("trade_date", "STRING"),
        ("owner_raw", "STRING"),
        ("ticker_raw", "STRING"),
        ("ticker", "STRING"),
        ("asset_name", "STRING"),
        ("asset_type", "STRING"),
        ("transaction_type_raw", "STRING"),
        ("amount_raw", "STRING"),
        ("comment", "STRING"),
        ("landing_key", "STRING"),
    ],
    "legislator_terms": [
        ("bioguide_id", "STRING"),
        ("first_name", "STRING"),
        ("last_name", "STRING"),
        ("nickname", "STRING"),
        ("official_full", "STRING"),
        ("term_type", "STRING"),
        ("term_start", "STRING"),
        ("term_end", "STRING"),
        ("state", "STRING"),
        ("district", "INT64"),
        ("party", "STRING"),
        ("landing_key", "STRING"),
    ],
    "committees": [
        ("committee_id", "STRING"),
        ("chamber", "STRING"),
        ("name", "STRING"),
        ("url", "STRING"),
        ("landing_key", "STRING"),
    ],
    "committee_membership": [
        ("snapshot_date", "STRING"),
        ("committee_id", "STRING"),
        ("bioguide_id", "STRING"),
        ("party", "STRING"),
        ("member_rank", "INT64"),
        ("title", "STRING"),
        ("landing_key", "STRING"),
    ],
    "sec_tickers": [
        ("ticker", "STRING"),
        ("cik", "INT64"),
        ("title", "STRING"),
        ("landing_key", "STRING"),
    ],
    "sec_companies": [
        ("cik", "INT64"),
        ("name", "STRING"),
        ("sic", "STRING"),
        ("sic_description", "STRING"),
        ("entity_type", "STRING"),
        ("landing_key", "STRING"),
    ],
    "prices": [
        ("ticker", "STRING"),
        ("price_date", "STRING"),
        ("close", "FLOAT64"),
        ("adj_close", "FLOAT64"),
        ("landing_key", "STRING"),
    ],
}


def _cached_house_parse(store: Store, key: str) -> house_p.ParsedReport:
    cache_key = f"parsed/house/v{HOUSE_PARSER_VERSION}/{key.rsplit('/', 1)[-1]}.json"
    if store.exists(cache_key):
        return house_p.ParsedReport(**json.loads(store.read(cache_key)))
    report = house_p.parse_pdf(store.read(key))
    store.write(cache_key, json.dumps(report.__dict__).encode(), "application/json")
    return report


def build_house(store: Store, years: Iterable[int]) -> tuple[list[dict], list[dict]]:
    filings, transactions = [], []
    for year in years:
        key = house_x.latest_index_key(store, year)
        if not key:
            continue
        for f in house_x.parse_index(store.read(key), year):
            row = f.as_row() | {"landed": store.exists(f.landing_key)}
            if row["landed"]:
                report = _cached_house_parse(store, f.landing_key)
                row |= {
                    "parse_status": report.status,
                    "parse_error": report.error,
                    "filer_name_on_report": report.filer_name,
                    "n_transactions": len(report.transactions),
                }
                for i, t in enumerate(report.transactions, start=1):
                    transactions.append(
                        t | {"doc_id": f.doc_id, "row_num": i, "landing_key": f.landing_key}
                    )
            else:
                row |= {"parse_status": "not_landed", "n_transactions": 0}
            filings.append(row)
    return filings, transactions


def build_senate(store: Store) -> tuple[list[dict], list[dict]]:
    reports, transactions = [], []
    for r in senate_x.load_reports(store):
        row = r.as_row() | {"landed": store.exists(r.landing_key), "n_transactions": 0}
        if r.kind == "paper":
            row["parse_status"] = "scanned"
        elif not row["landed"]:
            row["parse_status"] = "not_landed"
        else:
            parsed = senate_p.parse_html(
                store.read(r.landing_key).decode("utf-8", errors="replace")
            )
            row |= {
                "parse_status": parsed["status"],
                "filed_date_on_report": parsed["filed_date"],
                "n_transactions": len(parsed["transactions"]),
            }
            for t in parsed["transactions"]:
                transactions.append(t | {"report_id": r.report_id, "landing_key": r.landing_key})
        reports.append(row)
    return reports, transactions


def build_legislators(store: Store, since: date) -> tuple[list[dict], list[dict]]:
    terms, committees = [], []
    for name in ("legislators-current", "legislators-historical"):
        key = ref_x.latest_run_key(store, "reference/legislators/", f"{name}.json")
        if not key:
            continue
        for person in json.loads(store.read(key)):
            n = person.get("name", {})
            for t in person.get("terms", []):
                if t.get("end", "") < since.isoformat():
                    continue
                terms.append(
                    {
                        "bioguide_id": person["id"]["bioguide"],
                        "first_name": n.get("first"),
                        "last_name": n.get("last"),
                        "nickname": n.get("nickname"),
                        "official_full": n.get("official_full"),
                        "term_type": t.get("type"),
                        "term_start": t.get("start"),
                        "term_end": t.get("end"),
                        "state": t.get("state"),
                        "district": t.get("district"),
                        "party": t.get("party"),
                        "landing_key": key,
                    }
                )
    key = ref_x.latest_run_key(store, "reference/legislators/", "committees-current.json")
    if key:
        for c in json.loads(store.read(key)):
            committees.append(
                {
                    "committee_id": c.get("thomas_id"),
                    "chamber": c.get("type"),
                    "name": c.get("name"),
                    "url": c.get("url"),
                    "landing_key": key,
                }
            )
    return terms, committees


def build_membership(store: Store) -> list[dict]:
    rows = []
    for key in store.list("reference/committee-membership/"):
        snapshot = key.rsplit("/", 1)[-1].removesuffix(".yaml")
        data = yaml.safe_load(store.read(key)) or {}
        for committee_id, members in data.items():
            if len(committee_id) != 4:  # subcommittees are e.g. HSAG03
                continue
            for m in members or []:
                rows.append(
                    {
                        "snapshot_date": snapshot,
                        "committee_id": committee_id,
                        "bioguide_id": m.get("bioguide"),
                        "party": m.get("party"),
                        "member_rank": m.get("rank"),
                        "title": m.get("title"),
                        "landing_key": key,
                    }
                )
    return rows


def build_sec(store: Store) -> tuple[list[dict], list[dict]]:
    tickers, companies = [], []
    key = ref_x.latest_run_key(store, "reference/sec/", "company_tickers.json")
    if key:
        for ticker, v in ref_x.sec_ticker_map(store.read(key)).items():
            tickers.append(
                {"ticker": ticker, "cik": v["cik"], "title": v["title"], "landing_key": key}
            )
    for ckey in store.list("reference/sec/companies/"):
        c = json.loads(store.read(ckey))
        companies.append(
            {
                "cik": c["cik"],
                "name": c.get("name"),
                "sic": c.get("sic") or None,
                "sic_description": c.get("sicDescription") or None,
                "entity_type": c.get("entityType"),
                "landing_key": ckey,
            }
        )
    return tickers, companies


def build_prices(store: Store) -> list[dict]:
    rows = []
    for key in store.list("prices/yahoo/"):
        payload = json.loads(store.read(key))
        if not payload.get("chart", {}).get("result"):
            continue
        ticker = key.rsplit("/", 1)[-1].removesuffix(".json")
        rows.extend(r | {"landing_key": key} for r in prices_x.parse_chart(payload, ticker))
    return rows


def traded_tickers(house_tx: list[dict], senate_tx: list[dict], since: date) -> set[str]:
    """Tickers of in-scope trades (stocks and stock options) since the coverage start."""
    out = set()
    for t in house_tx:
        if (
            t.get("ticker")
            and t.get("asset_type") in ("ST", "OP")
            and (t.get("trade_date") or "") >= since.isoformat()
        ):
            out.add(t["ticker"])
    for t in senate_tx:
        if (
            t.get("ticker")
            and t.get("asset_type") in ("Stock", "Stock Option")
            and (t.get("trade_date") or "") >= since.isoformat()
        ):
            out.add(t["ticker"])
    return out
