"""House Clerk: yearly filing index plus every periodic transaction report PDF.

The Clerk publishes one zip per year (``{year}FD.zip``) listing every
financial disclosure filed that year. Rows with ``FilingType == "P"`` are
periodic transaction reports (PTRs), and each has a PDF at a predictable URL.

Landing layout:

- ``house/index/{year}/{run_date}/{year}FD.zip``: a fresh copy each run,
  because the index grows daily. Keeping each day's copy is the audit trail.
- ``house/ptr/{year}/{doc_id}.pdf``: filed reports never change, so each is
  downloaded once and skipped on later runs.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import asdict, dataclass
from datetime import date

from congress_trades.http_client import PoliteSession
from congress_trades.storage import Store

log = logging.getLogger(__name__)

BASE = "https://disclosures-clerk.house.gov/public_disc"
PTR_TYPE = "P"


@dataclass(frozen=True)
class HouseFiling:
    doc_id: str
    year: int
    prefix: str
    first: str
    last: str
    suffix: str
    state_district: str
    filing_date: str | None  # ISO date, or None when the index leaves it blank
    filing_type: str

    @property
    def pdf_url(self) -> str:
        return f"{BASE}/ptr-pdfs/{self.year}/{self.doc_id}.pdf"

    @property
    def landing_key(self) -> str:
        return f"house/ptr/{self.year}/{self.doc_id}.pdf"

    def as_row(self) -> dict:
        return asdict(self) | {"pdf_url": self.pdf_url, "landing_key": self.landing_key}


def index_key(year: int, run_date: date) -> str:
    return f"house/index/{year}/{run_date.isoformat()}/{year}FD.zip"


def latest_index_key(store: Store, year: int) -> str | None:
    keys = [k for k in store.list(f"house/index/{year}/") if k.endswith("FD.zip")]
    return max(keys) if keys else None


def download_index(session: PoliteSession, store: Store, year: int, run_date: date) -> str:
    key = index_key(year, run_date)
    if not store.exists(key):
        resp = session.get(f"{BASE}/financial-pdfs/{year}FD.zip")
        resp.raise_for_status()
        store.write(key, resp.content, "application/zip")
        log.info("house index %s: %s bytes", year, len(resp.content))
    return key


def parse_index(zip_bytes: bytes, year: int) -> list[HouseFiling]:
    """Read the tab-separated index inside the yearly zip and keep PTRs only."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        text = zf.read(name).decode("utf-8-sig", errors="replace")

    filings = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if (row.get("FilingType") or "").strip() != PTR_TYPE:
            continue
        doc_id = (row.get("DocID") or "").strip()
        if not doc_id.isdigit():
            continue
        filed = (row.get("FilingDate") or "").strip()
        filed_iso = None
        if filed:
            m, d, y = filed.split("/")
            filed_iso = date(int(y), int(m), int(d)).isoformat()
        filings.append(
            HouseFiling(
                doc_id=doc_id,
                year=year,
                prefix=(row.get("Prefix") or "").strip(),
                first=(row.get("First") or "").strip(),
                last=(row.get("Last") or "").strip(),
                suffix=(row.get("Suffix") or "").strip(),
                state_district=(row.get("StateDst") or "").strip(),
                filing_date=filed_iso,
                filing_type=PTR_TYPE,
            )
        )
    return filings


def download_ptrs(session: PoliteSession, store: Store, filings: list[HouseFiling]) -> dict:
    """Download every PTR PDF not already in the landing zone."""
    stats = {"already_landed": 0, "downloaded": 0, "missing": 0}
    for f in filings:
        if store.exists(f.landing_key):
            stats["already_landed"] += 1
            continue
        resp = session.get(f.pdf_url)
        if resp.status_code == 404 or not resp.content.startswith(b"%PDF"):
            stats["missing"] += 1
            log.warning("house ptr %s not available (%s)", f.doc_id, resp.status_code)
            continue
        resp.raise_for_status()
        store.write(f.landing_key, resp.content, "application/pdf")
        stats["downloaded"] += 1
    return stats


def extract(session: PoliteSession, store: Store, years: list[int], run_date: date) -> dict:
    stats = {"filings": 0, "already_landed": 0, "downloaded": 0, "missing": 0}
    for year in years:
        key = download_index(session, store, year, run_date)
        filings = parse_index(store.read(key), year)
        stats["filings"] += len(filings)
        for k, v in download_ptrs(session, store, filings).items():
            stats[k] += v
    log.info("house extract: %s", stats)
    return stats
