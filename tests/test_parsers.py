from congress_trades.parse.common import amount_band, normalize_ticker, transaction_type
from congress_trades.parse.house import parse_text
from congress_trades.parse.senate import parse_html

HOUSE_TEXT = """Filing ID #20024346
Name: Hon. Example Member
State/District: PA08
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
JT Alphabet Inc. - Class C Capital Stock S 01/13/2025 01/13/2025 $1,001 - $15,000
(GOOG) [ST]
F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New
S\x00\x00\x00 O\x00: Joint Ownership LPL Account
Berkshire Hathaway Inc. New P 01/15/2025 01/15/2025 $50,001 -
Common Stock (BRK.B) [OP] $100,000
F\x00 S\x00: New
D\x00: CALL BERKSHIRE CL B NEW $300 EXP 01/17/25
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/
"""

SENATE_HTML = """<h2>Filed  11/17/2026 @ 1:17 PM</h2><table><thead><tr>
<th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th><th>Asset Name</th>
<th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th></tr></thead><tbody>
<tr><td>1</td><td> 10/21/2026 </td><td>Joint</td><td><a href="#">TLH</a></td>
<td> iShares 10-20 Year Treasury Bond ETF </td><td>Stock</td><td>Sale (Partial)</td>
<td>$1,001 - $15,000</td><td>--</td></tr></tbody></table>"""


def test_amount_bands():
    assert amount_band("$1,001 - $15,000") == 0
    assert amount_band("$50,001 -\n$100,000") == 2
    assert amount_band("Over $50,000,000") == 9
    assert amount_band("Spouse/DC Over $1,000,000") == 6
    assert amount_band("$1,000 - $15,000") == 0
    assert amount_band("unknown") is None


def test_ticker_and_type_normalization():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker("--") is None
    assert transaction_type("S (partial)") == "sell"
    assert transaction_type("Sale (Full)") == "sell"
    assert transaction_type("Purchase") == "buy"


def test_house_report_rows():
    report = parse_text(HOUSE_TEXT)

    assert report.status == "parsed"
    assert report.state_district == "PA08"
    first, second = report.transactions
    assert first["owner_code"] == "JT"
    assert first["ticker"] == "GOOG"
    assert first["asset_name"] == "Alphabet Inc. - Class C Capital Stock"
    assert first["filing_status"] == "New"
    assert first["subholding_of"] == "Joint Ownership LPL Account"
    assert second["ticker"] == "BRK-B"
    assert second["asset_type"] == "OP"
    assert second["amount_raw"] == "$50,001 - $100,000"
    assert second["trade_date"] == "2025-01-15"
    assert second["description"].startswith("CALL BERKSHIRE")


def test_house_scanned_report():
    assert parse_text("").status == "scanned"


def test_senate_report_rows():
    parsed = parse_html(SENATE_HTML)

    assert parsed["status"] == "parsed"
    assert parsed["filed_date"] == "2026-11-17"
    (row,) = parsed["transactions"]
    assert row["ticker"] == "TLH"
    assert row["trade_date"] == "2026-10-21"
    assert row["comment"] is None
