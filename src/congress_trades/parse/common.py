"""Helpers shared by the House and Senate parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

# The ten value bands printed on both chambers' periodic transaction report
# forms. Index in this list is the `amount_band` used everywhere downstream.
AMOUNT_BANDS: list[tuple[int, int | None]] = [
    (1_001, 15_000),
    (15_001, 50_000),
    (50_001, 100_000),
    (100_001, 250_000),
    (250_001, 500_000),
    (500_001, 1_000_000),
    (1_000_001, 5_000_000),
    (5_000_001, 25_000_000),
    (25_000_001, 50_000_000),
    (50_000_001, None),
]

_MONEY = re.compile(r"\$\s*([\d,]+)")


def amount_band(text: str) -> int | None:
    """Map a disclosed amount such as '$1,001 - $15,000' to its band index.

    Handles 'Over $50,000,000', the spouse-only 'Over $1,000,000' line (which
    is mapped to the band starting at $1,000,001), and stray whitespace from
    PDF line breaks. Returns None when no band can be identified.
    """
    clean = " ".join(text.split())
    values = [int(v.replace(",", "")) for v in _MONEY.findall(clean)]
    if not values:
        return None
    low = values[0]
    if "over" in clean.lower():
        low += 1  # "Over $1,000,000" means $1,000,001 and up
    if low == 1_000:
        low = 1_001  # a few rows are written "$1,000 - $15,000"
    for i, (lo, hi) in enumerate(AMOUNT_BANDS):
        if lo <= low and (hi is None or low <= hi):
            return i
    return None


def parse_us_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_ticker(raw: str | None) -> str | None:
    """Uppercase, strip, and use the dash form for share classes (BRK.B -> BRK-B).

    The dash form is what both SEC EDGAR's ticker file and the price source use.
    """
    if not raw:
        return None
    t = raw.strip().upper().replace(".", "-").replace("/", "-")
    t = re.sub(r"[^A-Z0-9-]", "", t)
    if not t or t in {"--", "N-A", "NA"} or len(t) > 10:
        return None
    return t


TRANSACTION_TYPES = {
    "P": "buy",
    "PURCHASE": "buy",
    "S": "sell",
    "S (PARTIAL)": "sell",
    "SALE": "sell",
    "SALE (FULL)": "sell",
    "SALE (PARTIAL)": "sell",
    "E": "exchange",
    "EXCHANGE": "exchange",
}


def transaction_type(raw: str) -> str | None:
    return TRANSACTION_TYPES.get(" ".join(raw.upper().split()))


OWNERS = {
    "": "Self",
    "SELF": "Self",
    "SP": "Spouse",
    "SPOUSE": "Spouse",
    "JT": "Joint",
    "JOINT": "Joint",
    "DC": "Dependent",
    "CHILD": "Dependent",
    "DEPENDENT": "Dependent",
}


def owner(raw: str | None) -> str:
    return OWNERS.get((raw or "").strip().upper(), "Self")
