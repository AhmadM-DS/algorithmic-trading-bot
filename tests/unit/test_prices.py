"""
test_prices.py
Unit tests for reading the latest trade per ticker
"""

#Standard Library
from datetime import datetime, timezone
from decimal import Decimal

#Third Party Libraries
import pytest
import requests
from alpaca.data.models import Trade

#Local Imports
from data.prices import LatestTrade, PriceUnavailable, get_latest_trades

class FakeDataClient:
    """Stands in for StockHistoricalDataClient: returns the trades it was built with, or raises"""

    def __init__(self, trades=None, error=None):
        self.trades = trades or {}
        self.error = error
        self.requests = []

    def get_stock_latest_trade(self, request):
        self.requests.append(request.to_request_fields())
        if self.error is not None:
            raise self.error
        return self.trades

def trade(symbol, price, at):
    """Build an alpaca-py Trade the way the latest-trades endpoint returns it"""
    return Trade(symbol, {"t": at, "p": price, "s": 100, "x": "V", "i": 1, "c": ["@"], "z": "C"})

def test_latest_trades_come_back_per_ticker_in_utc():
    """Return each ticker's price as a Decimal and its time in UTC from one request"""
    at = "2026-11-09T15:00:05.123Z"
    client = FakeDataClient({"AAPL": trade("AAPL", 4.32, at)})

    trades = get_latest_trades(client, ["AAPL", "THIN"], "iex")

    assert trades == {"AAPL": LatestTrade(Decimal("4.32"), datetime(2026, 11, 9, 15, 0, 5, 123000, tzinfo=timezone.utc))}
    assert client.requests == [{"symbols": "AAPL,THIN", "feed": "iex"}]

def test_no_tickers_means_no_request():
    client = FakeDataClient()

    assert (get_latest_trades(client, [], "iex"), client.requests) == ({}, [])

def test_no_answer_raises_price_unavailable():
    client = FakeDataClient(error=requests.exceptions.Timeout("read timed out"))

    with pytest.raises(PriceUnavailable):
        get_latest_trades(client, ["AAPL"], "sip")
