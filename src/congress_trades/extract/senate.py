"""Senate eFD: search for periodic transaction reports and download each one.

The Senate site asks visitors to accept a usage agreement before searching
(the data may not be used for commercial purposes, credit ratings or
soliciting money; this project is non-commercial research). The extractor
accepts it the same way a browser does, then pages through the JSON search
endpoint the site's own search page uses.

Electronic reports are HTML pages with a transaction table. Paper reports
are scanned images; they are recorded but routed to manual review.

Landing layout:

- ``senate/search/{run_date}/page-{n:03d}.json``: each run's search results.
- ``senate/ptr/{report_id}.html``: electronic reports, downloaded once.
- ``senate/paper/{report_id}.html``: the viewer page for paper reports.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date

from congress_trades.http_client import PoliteSession
from congress_trades.storage import Store

log = logging.getLogger(__name__)

BASE = "https://efdsearch.senate.gov"
PTR_REPORT_TYPE = 11
PAGE_SIZE = 100
_LINK = re.compile(
    r'href="(?P<path>/search/view/(?P<kind>ptr|paper)/(?P<id>[0-9a-fA-F-]+)/)"[^>]*>(?P<title>[^<]*)<'
)


@dataclass(frozen=True)
class SenateReport:
    report_id: str
    kind: str  # "ptr" (electronic) or "paper" (scanned)
    first: str
    last: str
    office: str
    title: str
    filing_date: str | None

    @property
    def url(self) -> str:
        return f"{BASE}/search/view/{self.kind}/{self.report_id}/"

    @property
    def landing_key(self) -> str:
        return f"senate/{self.kind}/{self.report_id}.html"

    @property
    def is_amendment(self) -> bool:
        return "amendment" in self.title.lower()

    def as_row(self) -> dict:
        return asdict(self) | {
            "url": self.url,
            "landing_key": self.landing_key,
            "is_amendment": self.is_amendment,
        }


def open_session(session: PoliteSession) -> None:
    """Accept the usage agreement so the search endpoint answers."""
    home = session.get(f"{BASE}/search/home/")
    home.raise_for_status()
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
    if not m:
        raise RuntimeError("Senate eFD home page changed: no CSRF token found")
    resp = session.post(
        f"{BASE}/search/home/",
        data={"prohibition_agreement": "1", "csrfmiddlewaretoken": m.group(1)},
        headers={"Referer": f"{BASE}/search/home/"},
    )
    resp.raise_for_status()


def search_page(session: PoliteSession, start: int, since: date) -> dict:
    csrf = session.cookies.get("csrftoken", "")
    resp = session.post(
        f"{BASE}/search/report/data/",
        data={
            "start": str(start),
            "length": str(PAGE_SIZE),
            "report_types": f"[{PTR_REPORT_TYPE}]",
            "filer_types": "[]",
            "submitted_start_date": since.strftime("%m/%d/%Y 00:00:00"),
            "submitted_end_date": "",
            "candidate_state": "",
            "senator_state": "",
            "office_id": "",
            "first_name": "",
            "last_name": "",
            "csrfmiddlewaretoken": csrf,
        },
        headers={"X-CSRFToken": csrf, "Referer": f"{BASE}/search/"},
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("result") != "ok":
        raise RuntimeError(f"Senate search failed: {payload}")
    return payload


def parse_search_rows(payload: dict) -> list[SenateReport]:
    reports = []
    for first, last, office, link_html, filed in payload["data"]:
        m = _LINK.search(link_html)
        if not m:
            log.warning("unrecognised Senate search row: %s", link_html)
            continue
        filed_iso = None
        if filed:
            mm, dd, yy = filed.split("/")
            filed_iso = date(int(yy), int(mm), int(dd)).isoformat()
        reports.append(
            SenateReport(
                report_id=m["id"].lower(),
                kind=m["kind"],
                first=first.strip(),
                last=last.strip(),
                office=office.strip(),
                title=" ".join(m["title"].split()),
                filing_date=filed_iso,
            )
        )
    return reports


def search_keys(store: Store) -> list[str]:
    """Search-result pages from the most recent run."""
    keys = [k for k in store.list("senate/search/") if k.endswith(".json")]
    if not keys:
        return []
    latest = max(k.split("/")[2] for k in keys)
    return sorted(k for k in keys if k.split("/")[2] == latest)


def load_reports(store: Store) -> list[SenateReport]:
    reports: dict[str, SenateReport] = {}
    for key in search_keys(store):
        for r in parse_search_rows(json.loads(store.read(key))):
            reports[r.report_id] = r
    return list(reports.values())


def extract(session: PoliteSession, store: Store, since: date, run_date: date) -> dict:
    open_session(session)
    stats = {"reports": 0, "already_landed": 0, "downloaded": 0, "paper": 0}
    start, page, reports = 0, 0, []
    while True:
        payload = search_page(session, start, since)
        store.write(
            f"senate/search/{run_date.isoformat()}/page-{page:03d}.json",
            json.dumps(payload).encode(),
            "application/json",
        )
        rows = parse_search_rows(payload)
        reports.extend(rows)
        start += PAGE_SIZE
        page += 1
        if not payload["data"] or start >= payload["recordsFiltered"]:
            break

    stats["reports"] = len(reports)
    for r in reports:
        if r.kind == "paper":
            stats["paper"] += 1
        if store.exists(r.landing_key):
            stats["already_landed"] += 1
            continue
        resp = session.get(r.url)
        if resp.status_code != 200 or "search/home" in resp.url:
            # The agreement cookie expired mid-run; accept again and retry once.
            open_session(session)
            resp = session.get(r.url)
        resp.raise_for_status()
        store.write(r.landing_key, resp.content, "text/html")
        stats["downloaded"] += 1
    log.info("senate extract: %s", stats)
    return stats
