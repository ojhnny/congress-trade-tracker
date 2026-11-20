"""Parse Senate eFD periodic transaction report pages into transaction rows.

Electronic Senate reports are HTML with one table whose columns are:
#, Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type, Amount,
Comment. The parser reads that table with the standard library's HTML
parser, so it needs no extra dependency.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from congress_trades.parse.common import normalize_ticker, parse_us_date

EXPECTED_HEADER = [
    "#",
    "Transaction Date",
    "Owner",
    "Ticker",
    "Asset Name",
    "Asset Type",
    "Type",
    "Amount",
    "Comment",
]
_FILED = re.compile(r"Filed\s+(\d{2}/\d{2}/\d{4})")


class _Tables(HTMLParser):
    """Collects every table as a list of rows of cell text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
            self._depth += 1
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table":
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_html(page: str) -> dict:
    """Return {"status", "filed_date", "transactions"} for one report page."""
    parser = _Tables()
    parser.feed(page)
    filed = _FILED.search(html.unescape(page))
    filed_date = parse_us_date(filed.group(1)) if filed else None
    out = {
        "status": "no_transactions",
        "filed_date": filed_date.isoformat() if filed_date else None,
        "transactions": [],
    }

    for table in parser.tables:
        if not table or table[0] != EXPECTED_HEADER:
            continue
        for row in table[1:]:
            if len(row) != len(EXPECTED_HEADER):
                continue
            num, tdate, owner, ticker, asset, asset_type, tx_type, amount, comment = row
            td = parse_us_date(tdate)
            out["transactions"].append(
                {
                    "row_num": int(num) if num.isdigit() else None,
                    "trade_date": td.isoformat() if td else None,
                    "owner_raw": owner,
                    "ticker_raw": ticker if ticker != "--" else None,
                    "ticker": normalize_ticker(ticker),
                    "asset_name": asset,
                    "asset_type": asset_type,
                    "transaction_type_raw": tx_type,
                    "amount_raw": amount,
                    "comment": None if comment == "--" else comment,
                }
            )
    if out["transactions"]:
        out["status"] = "parsed"
    return out
