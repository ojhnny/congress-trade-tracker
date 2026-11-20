"""Parse House periodic transaction report PDFs into transaction rows.

Electronically filed House PTRs are text PDFs with a fixed layout. Each
transaction starts on a line that ends with the transaction type, two dates
and the amount:

    JT Alphabet Inc. - Class C Capital Stock S 01/13/2025 01/13/2025 $1,001 - $15,000
    (GOOG) [ST]
    F      S     : New
    S          O : Joint Ownership LPL Account

The asset name can wrap onto the next lines, and so can the upper end of the
amount ("$50,001 -" then "(GOOG) [ST] $100,000"). Small-caps labels such as
"FILING STATUS" come out of the PDF as "F S", so the parser matches their
first letters rather than the full words.

Paper filings are scanned images with no text layer. They are reported as
``scanned`` and routed to manual review instead of being guessed at.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

from congress_trades.parse.common import normalize_ticker, parse_us_date

log = logging.getLogger(__name__)

ROW_START = re.compile(
    r"^(?:(?P<owner>SP|JT|DC)\s+)?"
    r"(?:(?P<asset>.*?)\s+)?"
    r"(?P<type>P|S \(partial\)|S|E)\s+"
    r"(?P<tdate>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<ndate>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>(?:Spouse/DC\s+)?(?:Over\s+)?\$[\d,]+.*)$"
)
STATUS = re.compile(r"^(?:F\s+S|FILING STATUS)\s*:\s*(?P<v>.+)$", re.I)
DESCRIPTION = re.compile(r"^(?:D|DESCRIPTION)\s*:\s*(?P<v>.*)$", re.I)
SUBHOLDING = re.compile(r"^(?:S\s+O|SUBHOLDING OF)\s*:\s*(?P<v>.*)$", re.I)
COMMENT = re.compile(r"^(?:C|COMMENTS?)\s*:\s*(?P<v>.*)$", re.I)
TRAILING_AMOUNT = re.compile(r"\s*(\$[\d,]+)\s*$")
TICKER = re.compile(r"\(([A-Za-z0-9.\-/ ]{1,12})\)")
ASSET_TYPE = re.compile(r"\[([A-Z0-9]{2})\]")
HEADER_LINES = ("ID Owner Asset", "Type Date Gains", "$200?")
END_MARKERS = (
    "* For the complete list of asset type",
    "I          V       D",
    "INITIAL PUBLIC OFFERINGS",
)


@dataclass
class _Row:
    owner: str | None
    asset_lines: list[str]
    tx_type: str
    trade_date: str
    notification_date: str
    amount: str
    filing_status: str | None = None
    description: str | None = None
    subholding_of: str | None = None
    comment: str | None = None
    closed: bool = False  # True once the status line ends the asset text

    def to_dict(self) -> dict:
        asset_text = " ".join(" ".join(self.asset_lines).split())
        tickers = TICKER.findall(asset_text)
        types = ASSET_TYPE.findall(asset_text)
        name = ASSET_TYPE.sub("", asset_text)
        if tickers:
            name = name.replace(f"({tickers[-1]})", "")
        td = parse_us_date(self.trade_date)
        nd = parse_us_date(self.notification_date)
        return {
            "owner_code": self.owner,
            "asset_text": asset_text,
            "asset_name": " ".join(name.split()).strip(" -"),
            "ticker_raw": tickers[-1].strip() if tickers else None,
            "ticker": normalize_ticker(tickers[-1]) if tickers else None,
            "asset_type": types[-1] if types else None,
            "transaction_type_raw": self.tx_type,
            "trade_date": td.isoformat() if td else None,
            "notification_date": nd.isoformat() if nd else None,
            "amount_raw": " ".join(self.amount.split()),
            "filing_status": self.filing_status,
            "description": self.description,
            "subholding_of": self.subholding_of,
            "comment": self.comment,
        }


@dataclass
class ParsedReport:
    status: str  # parsed | scanned | no_transactions | failed
    transactions: list[dict] = field(default_factory=list)
    filer_name: str | None = None
    state_district: str | None = None
    error: str | None = None


def pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber  # heavy import kept local so the DAG processor stays fast

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_text(text: str) -> ParsedReport:
    """Parse the extracted text of one report. Pure function, easy to test."""
    # Small-caps labels come out as letters separated by NUL characters.
    text = text.replace("\x00", "")
    if "Filing ID" not in text and not ROW_START.search(text):
        return ParsedReport(status="scanned")

    report = ParsedReport(status="parsed")
    rows: list[_Row] = []
    current: _Row | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Name:"):
            report.filer_name = line.removeprefix("Name:").strip()
            continue
        if line.startswith("State/District:"):
            report.state_district = line.removeprefix("State/District:").strip()
            continue
        if line.startswith(HEADER_LINES):
            continue
        if line.startswith(END_MARKERS):
            current = None
            continue

        m = ROW_START.match(line)
        if m:
            current = _Row(
                owner=m["owner"],
                asset_lines=[m["asset"]] if m["asset"] else [],
                tx_type=m["type"],
                trade_date=m["tdate"],
                notification_date=m["ndate"],
                amount=m["amount"],
            )
            rows.append(current)
            continue
        if current is None:
            continue

        for pattern, attr in (
            (STATUS, "filing_status"),
            (SUBHOLDING, "subholding_of"),
            (DESCRIPTION, "description"),
            (COMMENT, "comment"),
        ):
            sm = pattern.match(line)
            if sm:
                setattr(current, attr, sm["v"].strip())
                current.closed = True
                break
        else:
            if current.closed:
                continue
            # Continuation of the asset name, possibly ending with the amount's upper bound.
            tm = TRAILING_AMOUNT.search(line)
            if tm and current.amount.rstrip().endswith("-"):
                current.amount = f"{current.amount} {tm.group(1)}"
                line = line[: tm.start()]
            if line:
                current.asset_lines.append(line)

    report.transactions = [r.to_dict() for r in rows]
    if not report.transactions:
        report.status = "no_transactions"
    return report


def parse_pdf(pdf_bytes: bytes) -> ParsedReport:
    try:
        text = pdf_text(pdf_bytes)
    except Exception as err:  # malformed PDFs exist; record and move on
        log.warning("could not read pdf: %s", err)
        return ParsedReport(status="failed", error=str(err)[:500])
    if len(text.strip()) < 40:
        return ParsedReport(status="scanned")
    return parse_text(text)
