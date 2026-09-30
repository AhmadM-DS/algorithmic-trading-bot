import pytest
from market_data import get_latest_price

#Helper classes to test code with no keys
class FakeTradeHelper:
    def __init__(self, price=100.67):
        self.price = price

class FakeClientHelper:
    def get_stock_latest_trade(self, request):
        return {"AAPL": FakeTradeHelper()}

def test_latest_price_matches():
    """Test if latest price of underlying stock matches with Alpaca's latest price"""
    assert get_latest_price(FakeClientHelper(), "AAPL") == 100.67