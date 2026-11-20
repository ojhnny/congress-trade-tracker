import pytest

from congress_trades.extract.reference import quarter_starts
from congress_trades.storage import LocalStore


def test_local_store_round_trip(tmp_path):
    store = LocalStore(tmp_path)
    store.write("house/ptr/2025/1.pdf", b"%PDF")

    assert store.exists("house/ptr/2025/1.pdf")
    assert store.read("house/ptr/2025/1.pdf") == b"%PDF"
    assert list(store.list("house/")) == ["house/ptr/2025/1.pdf"]


def test_local_store_rejects_escaping_keys(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).write("../outside.txt", b"x")


def test_quarter_starts():
    from datetime import date

    assert quarter_starts(date(2024, 2, 10), date(2024, 12, 31)) == [
        date(2024, 1, 1),
        date(2024, 4, 1),
        date(2024, 7, 1),
        date(2024, 10, 1),
    ]
