"""Generate sample data for the dashboard until the real pipeline exists.

The output has exactly the shape the pipeline's export step will produce from
the dbt marts, so the frontend never has to change when real data arrives.

Everything here is invented. Members are fictional people; tickers and
committees are real so the page reads naturally. The JSON carries
`"sample": true` and the site shows a banner while that flag is set.

Run:  python frontend/scripts/make_sample_data.py
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261018
AS_OF = date(2026, 10, 15)
START = date(2024, 1, 2)
OUT = Path(__file__).resolve().parents[1] / "data" / "dashboard.json"

# Disclosure bands from the House and Senate periodic transaction report forms.
AMOUNT_BANDS = [
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
BAND_WEIGHTS = [52, 22, 10, 8, 4, 2, 1.4, 0.4, 0.15, 0.05]

# ticker, company, sector
SECURITIES = [
    ("JPM", "JPMorgan Chase & Co.", "Banks & Finance"),
    ("BAC", "Bank of America Corp.", "Banks & Finance"),
    ("GS", "Goldman Sachs Group Inc.", "Banks & Finance"),
    ("WFC", "Wells Fargo & Co.", "Banks & Finance"),
    ("V", "Visa Inc.", "Banks & Finance"),
    ("SCHW", "Charles Schwab Corp.", "Banks & Finance"),
    ("XOM", "Exxon Mobil Corp.", "Oil, Gas & Mining"),
    ("CVX", "Chevron Corp.", "Oil, Gas & Mining"),
    ("COP", "ConocoPhillips", "Oil, Gas & Mining"),
    ("FCX", "Freeport-McMoRan Inc.", "Oil, Gas & Mining"),
    ("OXY", "Occidental Petroleum Corp.", "Oil, Gas & Mining"),
    ("NEE", "NextEra Energy Inc.", "Utilities"),
    ("DUK", "Duke Energy Corp.", "Utilities"),
    ("SO", "Southern Co.", "Utilities"),
    ("LMT", "Lockheed Martin Corp.", "Defense & Aerospace"),
    ("RTX", "RTX Corp.", "Defense & Aerospace"),
    ("NOC", "Northrop Grumman Corp.", "Defense & Aerospace"),
    ("GD", "General Dynamics Corp.", "Defense & Aerospace"),
    ("BA", "Boeing Co.", "Defense & Aerospace"),
    ("UNH", "UnitedHealth Group Inc.", "Health Care"),
    ("PFE", "Pfizer Inc.", "Health Care"),
    ("LLY", "Eli Lilly & Co.", "Health Care"),
    ("JNJ", "Johnson & Johnson", "Health Care"),
    ("MRK", "Merck & Co. Inc.", "Health Care"),
    ("NVDA", "NVIDIA Corp.", "Technology"),
    ("MSFT", "Microsoft Corp.", "Technology"),
    ("AAPL", "Apple Inc.", "Technology"),
    ("AMD", "Advanced Micro Devices Inc.", "Technology"),
    ("CRM", "Salesforce Inc.", "Technology"),
    ("GOOGL", "Alphabet Inc.", "Telecom & Media"),
    ("META", "Meta Platforms Inc.", "Telecom & Media"),
    ("T", "AT&T Inc.", "Telecom & Media"),
    ("VZ", "Verizon Communications Inc.", "Telecom & Media"),
    ("DIS", "Walt Disney Co.", "Telecom & Media"),
    ("DE", "Deere & Co.", "Agriculture & Food"),
    ("ADM", "Archer-Daniels-Midland Co.", "Agriculture & Food"),
    ("TSN", "Tyson Foods Inc.", "Agriculture & Food"),
    ("CTVA", "Corteva Inc.", "Agriculture & Food"),
    ("UNP", "Union Pacific Corp.", "Transportation"),
    ("DAL", "Delta Air Lines Inc.", "Transportation"),
    ("UPS", "United Parcel Service Inc.", "Transportation"),
    ("F", "Ford Motor Co.", "Transportation"),
    ("GM", "General Motors Co.", "Transportation"),
    ("AMZN", "Amazon.com Inc.", "Retail & Consumer"),
    ("COST", "Costco Wholesale Corp.", "Retail & Consumer"),
    ("WMT", "Walmart Inc.", "Retail & Consumer"),
    ("PLD", "Prologis Inc.", "Real Estate"),
    ("AMT", "American Tower Corp.", "Real Estate"),
]
SECTOR_WEIGHT = {
    "Technology": 24, "Banks & Finance": 13, "Health Care": 12, "Telecom & Media": 10,
    "Retail & Consumer": 8, "Oil, Gas & Mining": 8, "Defense & Aerospace": 6,
    "Transportation": 6, "Utilities": 4, "Agriculture & Food": 4, "Real Estate": 5,
}

# Real committees, with the sectors this project maps to their jurisdiction.
# The real mapping table is built by hand in a later section; this is a stand-in.
COMMITTEES = [
    ("HSBA", "Financial Services", "House", ["Banks & Finance", "Real Estate"]),
    ("HSIF", "Energy and Commerce", "House",
     ["Oil, Gas & Mining", "Utilities", "Health Care", "Telecom & Media"]),
    ("HSAS", "Armed Services", "House", ["Defense & Aerospace"]),
    ("HSAG", "Agriculture", "House", ["Agriculture & Food"]),
    ("HSPW", "Transportation and Infrastructure", "House", ["Transportation"]),
    ("HSWM", "Ways and Means", "House", ["Health Care"]),
    ("HSSY", "Science, Space, and Technology", "House", ["Technology"]),
    ("SSBK", "Banking, Housing, and Urban Affairs", "Senate", ["Banks & Finance", "Real Estate"]),
    ("SSAS", "Armed Services", "Senate", ["Defense & Aerospace"]),
    ("SSCM", "Commerce, Science, and Transportation", "Senate",
     ["Transportation", "Telecom & Media", "Technology"]),
    ("SSEG", "Energy and Natural Resources", "Senate", ["Oil, Gas & Mining", "Utilities"]),
    ("SSHR", "Health, Education, Labor, and Pensions", "Senate", ["Health Care"]),
    ("SSAF", "Agriculture, Nutrition, and Forestry", "Senate", ["Agriculture & Food"]),
]

FIRST = ["Dana", "Marcus", "Elena", "Graham", "Priya", "Walt", "Renee", "Tobias", "Lorna",
         "Hector", "Joan", "Calvin", "Ines", "Russell", "Mara", "Desmond", "Celia", "Owen",
         "Beatrix", "Leon", "Sonia", "Garrett", "Noor", "Phil", "Tamsin", "Abel", "Yvette",
         "Curtis", "Helena", "Raymond", "Odette", "Simon", "Kendra", "Martin", "Lucia", "Vince"]
LAST = ["Whitcombe", "Arland", "Pruett", "Castellan", "Okafor", "Brennick", "Halvorsen",
        "Vasquez-Lin", "Dunmore", "Ellery", "Thorne", "Mabry", "Kessling", "Abernath",
        "Quayle-Ruiz", "Stroud", "Wexley", "Ferrante", "Lindqvist", "Ashdown", "Corrigan",
        "Delacroix", "Ivers", "Pemberton", "Rasmund", "Tolliver", "Ostrander", "Galloway",
        "Hartigan", "Merriweather", "Sandoval", "Yarrow", "Bellamy", "Fairbanks", "Calloway",
        "Nyland", "Brightwater", "Lockridge", "Sorensen", "Varga"]
STATES = ["CA", "TX", "FL", "NY", "PA", "OH", "GA", "NC", "IL", "VA", "AZ", "WA", "TN",
          "CO", "MN", "WI", "MO", "IN", "SC", "AL", "KY", "OR", "NJ", "MA", "LA"]


def make_members(rng: random.Random) -> list[dict]:
    names = set()

    def new_name() -> str:
        while True:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if n not in names:
                names.add(n)
                return n

    members = []

    def add(chamber: str, state: str, district: int | None, party: str) -> None:
        pool = [c for c in COMMITTEES if c[2] == chamber]
        k = rng.choice([1, 2, 2, 3]) if chamber == "Senate" else rng.choice([1, 1, 2, 2, 3])
        comms = rng.sample(pool, k)
        members.append({
            "id": f"S{len(members) + 1:04d}",
            "name": new_name(),
            "party": party,
            "chamber": chamber,
            "state": state,
            "district": district,
            "committees": [c[0] for c in comms],
            # hidden traits used only by this generator
            "_activity": rng.paretovariate(1.25),
            "_late_prone": rng.random() < 0.18,
        })

    # Michigan: full delegation, 13 House districts and 2 senators.
    mi_parties = ["R", "R", "R", "R", "R", "D", "D", "R", "R", "R", "D", "D", "D"]
    for d, p in enumerate(mi_parties, start=1):
        add("House", "MI", d, p)
    add("Senate", "MI", None, "D")
    add("Senate", "MI", None, "D")

    for _ in range(55):
        add("House", rng.choice(STATES), rng.randint(1, 12), rng.choice("DDRRR" if rng.random() < .5 else "DDDRR"))
    for _ in range(18):
        add("Senate", rng.choice(STATES), None, rng.choice(["D", "R", "R", "D", "D", "R", "I"]))
    return members


def pick_lag(rng: random.Random, late_prone: bool) -> int:
    r = rng.random()
    late_share = 0.34 if late_prone else 0.07
    if r < late_share:
        r2 = rng.random()
        if r2 < 0.55:
            return rng.randint(46, 75)
        if r2 < 0.92:
            return rng.randint(76, 180)
        return rng.randint(181, 420)
    if r < late_share + 0.12:
        return rng.randint(38, 45)
    return max(2, int(rng.triangular(3, 37, 24)))


def make_trades(rng: random.Random, members: list[dict]) -> list[dict]:
    comm_sectors = {c[0]: c[3] for c in COMMITTEES}
    by_sector: dict[str, list[tuple]] = {}
    for s in SECURITIES:
        by_sector.setdefault(s[2], []).append(s)
    sectors = list(SECTOR_WEIGHT)
    weights = [SECTOR_WEIGHT[s] for s in sectors]

    trades = []
    days = (AS_OF - START).days
    for m in members:
        n = min(140, int(m["_activity"] * 6)) if rng.random() < 0.85 else 0
        overseen = sorted({s for c in m["committees"] for s in comm_sectors[c]})
        for _ in range(n):
            if overseen and rng.random() < 0.22:
                sector = rng.choice(overseen)
            else:
                sector = rng.choices(sectors, weights)[0]
            ticker, company, sector = rng.choice(by_sector[sector])
            traded = START + timedelta(days=rng.randint(0, days - 3))
            lag = pick_lag(rng, m["_late_prone"])
            filed = traded + timedelta(days=lag)
            if filed > AS_OF:
                continue
            band = rng.choices(range(len(AMOUNT_BANDS)), BAND_WEIGHTS)[0]
            lo, hi = AMOUNT_BANDS[band]
            kind = rng.choices(["buy", "sell", "exchange"], [55, 42, 3])[0]
            overlap = next((c for c in m["committees"] if sector in comm_sectors[c]), None)
            def ret(sd: float) -> float | None:
                return round(rng.gauss(0.002, sd), 4)
            r30 = ret(0.055) if (AS_OF - traded).days >= 30 else None
            r90 = ret(0.095) if (AS_OF - traded).days >= 90 else None
            trades.append({
                "member_id": m["id"],
                "ticker": ticker,
                "company": company,
                "sector": sector,
                "type": kind,
                "owner": rng.choices(["Self", "Spouse", "Joint", "Dependent"], [45, 35, 15, 5])[0],
                "amount_band": band,
                "amount_min": lo,
                "amount_max": hi,
                "trade_date": traded.isoformat(),
                "filed_date": filed.isoformat(),
                "days_to_file": lag,
                "overlap_committee": overlap,
                "excess_return_30d": r30,
                "excess_return_90d": r90,
            })
    trades.sort(key=lambda t: (t["filed_date"], t["trade_date"]), reverse=True)
    for i, t in enumerate(trades, start=1):
        t["id"] = f"T{i:05d}"
    return trades


def main() -> None:
    rng = random.Random(SEED)
    members = make_members(rng)
    trades = make_trades(rng, members)
    for m in members:
        for k in [k for k in m if k.startswith("_")]:
            del m[k]

    payload = {
        "meta": {
            "sample": True,
            "as_of": AS_OF.isoformat(),
            "coverage_start": START.isoformat(),
            "benchmark": "SPY",
            "amount_bands": [{"min": lo, "max": hi} for lo, hi in AMOUNT_BANDS],
            "pipeline": {
                "filings_downloaded": 3412,
                "filings_parsed": 3366,
                "scanned_needing_review": 46,
                "amendments_superseded": 129,
                "tickers_unmatched": 38,
                "rows_reconciled": True,
            },
        },
        "committees": [
            {"id": c[0], "name": c[1], "chamber": c[2], "sectors": c[3]} for c in COMMITTEES
        ],
        "members": members,
        "trades": trades,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {OUT} with {len(members)} members and {len(trades)} trades")


if __name__ == "__main__":
    main()
