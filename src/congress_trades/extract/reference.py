"""Reference data: members, committees, committee membership history, SEC tickers.

Sources:

- ``unitedstates/congress-legislators`` publishes current and historical
  members (with every term served) and current committees. Its committee
  *membership* file only ever describes today, so the project rebuilds the
  history from the repository's git history: one snapshot of
  ``committee-membership-current.yaml`` per quarter, taken from the last
  commit before that quarter began. Each snapshot is valid until the next
  one, which is what turns into the bridge table's valid_from/valid_to.
- SEC EDGAR's ``company_tickers.json`` maps tickers to CIKs, and each
  company's submissions record carries its SIC industry code. The full
  submissions record is large (it lists every filing), so only the identity
  and industry fields are kept.

Landing layout:

- ``reference/legislators/{run_date}/{file}.json``
- ``reference/committee-membership/{snapshot_date}.yaml``
- ``reference/sec/{run_date}/company_tickers.json``
- ``reference/sec/companies/{cik}.json``
"""

from __future__ import annotations

import json
import logging
from datetime import date

from congress_trades.http_client import PoliteSession
from congress_trades.storage import Store

log = logging.getLogger(__name__)

LEGISLATORS = "https://unitedstates.github.io/congress-legislators"
LEGISLATOR_FILES = ("legislators-current", "legislators-historical", "committees-current")
GITHUB_API = "https://api.github.com/repos/unitedstates/congress-legislators"
RAW_GITHUB = "https://raw.githubusercontent.com/unitedstates/congress-legislators"
MEMBERSHIP_FILE = "committee-membership-current.yaml"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_KEEP = ("cik", "name", "sic", "sicDescription", "tickers", "exchanges", "entityType")


def quarter_starts(since: date, until: date) -> list[date]:
    """First day of every quarter from the one containing `since` through `until`."""
    q = date(since.year, 3 * ((since.month - 1) // 3) + 1, 1)
    out = []
    while q <= until:
        out.append(q)
        q = date(q.year + (q.month == 10), (q.month + 2) % 12 + 1, 1)
    return out


def latest_run_key(store: Store, prefix: str, filename: str) -> str | None:
    keys = [k for k in store.list(prefix) if k.endswith("/" + filename)]
    return max(keys) if keys else None


def extract_legislators(session: PoliteSession, store: Store, run_date: date) -> None:
    for name in LEGISLATOR_FILES:
        key = f"reference/legislators/{run_date.isoformat()}/{name}.json"
        if store.exists(key):
            continue
        resp = session.get(f"{LEGISLATORS}/{name}.json")
        resp.raise_for_status()
        store.write(key, resp.content, "application/json")


def extract_membership_history(
    session: PoliteSession, store: Store, since: date, today: date
) -> int:
    """Land one membership snapshot per quarter, plus today's current file."""
    fetched = 0
    for snap in quarter_starts(since, today):
        key = f"reference/committee-membership/{snap.isoformat()}.yaml"
        if store.exists(key):
            continue
        commits = session.get(
            f"{GITHUB_API}/commits",
            params={
                "path": MEMBERSHIP_FILE,
                "until": f"{snap.isoformat()}T00:00:00Z",
                "per_page": 1,
            },
            headers={"Accept": "application/vnd.github+json"},
        )
        commits.raise_for_status()
        if not commits.json():
            continue
        sha = commits.json()[0]["sha"]
        resp = session.get(f"{RAW_GITHUB}/{sha}/{MEMBERSHIP_FILE}")
        resp.raise_for_status()
        store.write(key, resp.content, "application/yaml")
        fetched += 1

    key = f"reference/committee-membership/{today.isoformat()}.yaml"
    if not store.exists(key):
        resp = session.get(f"{RAW_GITHUB}/main/{MEMBERSHIP_FILE}")
        resp.raise_for_status()
        store.write(key, resp.content, "application/yaml")
        fetched += 1
    return fetched


def extract_sec_tickers(session: PoliteSession, store: Store, run_date: date) -> str:
    key = f"reference/sec/{run_date.isoformat()}/company_tickers.json"
    if not store.exists(key):
        resp = session.get(SEC_TICKERS)
        resp.raise_for_status()
        store.write(key, resp.content, "application/json")
    return key


def sec_ticker_map(raw: bytes) -> dict[str, dict]:
    """ticker (dash form) -> {"cik", "title"}."""
    out = {}
    for row in json.loads(raw).values():
        ticker = str(row["ticker"]).upper().replace(".", "-")
        out.setdefault(ticker, {"cik": int(row["cik_str"]), "title": row["title"]})
    return out


def extract_sec_companies(session: PoliteSession, store: Store, ciks: set[int]) -> int:
    """Land identity and SIC fields for each CIK not yet landed."""
    fetched = 0
    for cik in sorted(ciks):
        key = f"reference/sec/companies/{cik}.json"
        if store.exists(key):
            continue
        resp = session.get(SEC_SUBMISSIONS.format(cik=cik))
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        full = resp.json()
        kept = {k: full.get(k) for k in SEC_KEEP} | {"cik": cik}
        store.write(key, json.dumps(kept).encode(), "application/json")
        fetched += 1
    log.info("sec companies fetched: %s", fetched)
    return fetched
