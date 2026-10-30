"""
test_orders.py
Unit tests for the pure parts of execution/orders.py: tick rounding, exit price check, client_order_id, requests
"""

#Standard Library
import re
from datetime import datetime
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from execution.orders import OrderRequest, exit_prices_valid, make_client_order_id, round_to_tick

NOW = datetime(2026, 10, 28, 14, 30, 5)

@pytest.mark.parametrize("price, expected", [(5.0234, "5.02"), (5.025, "5.03"), (5.0, "5.00"), (12.999, "13.00"),
                                             (1, "1.00"), (0.51237, "0.5124"), (0.51235, "0.5124"),
                                             (0.9999, "0.9999"), (Decimal("3.456"), "3.46")])
def test_round_to_tick(price, expected):
    """Round to cents at $1 or more and to 4 decimals below $1, halves going up"""

    assert round_to_tick(price) == Decimal(expected)

def test_round_to_tick_keeps_exact_decimal_digits():
    """Return a Decimal with exactly the tick's number of decimals"""

    assert str(round_to_tick(7)) == "7.00"
    assert str(round_to_tick(0.5)) == "0.5000"

@pytest.mark.parametrize("stop, target, valid", [("4.90", "5.20", True), ("4.99", "5.01", True),
                                                 ("5.00", "5.20", False), ("4.995", "5.20", False),
                                                 ("4.90", "5.00", False), ("4.90", "5.005", False),
                                                 ("0", "5.20", False)])
def test_exit_prices_valid(stop, target, valid):
    """Need the stop at least a cent below the price, the target at least a cent above, and the stop above 0"""

    assert exit_prices_valid(Decimal("5.00"), Decimal(stop), Decimal(target)) is valid

def test_client_order_id_format():
    """Build strategy-ticker-side-UTC time-4 random hex"""

    client_order_id = make_client_order_id("momentum", "AAPL", "buy", NOW)

    assert re.fullmatch(r"momentum-AAPL-buy-20261028T143005Z-[0-9a-f]{4}", client_order_id)

def test_client_order_ids_differ_in_the_same_second():
    """Make two orders in the same second still get different IDs"""

    ids = {make_client_order_id("momentum", "AAPL", "buy", NOW) for _ in range(20)}

    assert len(ids) > 1

def test_client_order_id_too_long_raises():
    """Refuse an ID longer than Alpaca's 128 characters"""

    with pytest.raises(ValueError, match="128"):
        make_client_order_id("x" * 120, "AAPL", "buy", NOW)

def request(**overrides):
    """Return a valid buy request with any field overridden"""
    values = {"strategy": "momentum", "strategy_id": 1, "ticker": "AAPL", "ticker_id": 1, "side": "buy",
              "quantity": 10, "holding_type": "day", "price": Decimal("5.00"), "stop_price": Decimal("4.90"),
              "target_price": Decimal("5.20")}
    values.update(overrides)
    return OrderRequest(**values)

def test_valid_requests_are_accepted():
    """Accept a buy with both exits and a sell with none"""

    request()
    request(side="sell", stop_price=None, target_price=None)

@pytest.mark.parametrize("overrides, message", [({"quantity": 0}, "quantity"), ({"quantity": -1}, "quantity"),
                                                ({"side": "short"}, "side"), ({"price": 0}, "price"),
                                                ({"holding_type": "scalp"}, "holding_type"),
                                                ({"stop_price": None}, "bracket"),
                                                ({"target_price": None}, "bracket")])
def test_invalid_requests_raise(overrides, message):
    """Refuse requests that can only come from a bug"""

    with pytest.raises(ValueError, match=message):
        request(**overrides)
