"""
test_broker.py
Unit tests for execution/broker.py and the session timeout, with a fake alpaca-py client
"""

#Standard Library
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

#Third Party Libraries
import pytest
import requests
from alpaca.common.exceptions import APIError
from alpaca.trading.models import Asset, Order, Position, TradeAccount

#Local Imports
from config.constants import ALPACA_TIMEOUT_SECONDS
from execution.broker import (AlpacaBroker, BrokerOrder, BrokerUnavailable, DuplicateOrder, OrderRejected)
from execution.rate_limiter import RateLimitedSession, RateLimiter

BUY_ID = "61e69015-8549-4bfd-b9c3-01e75843f47d"
TARGET_ID = "6f1e2d3c-0000-4000-8000-000000000002"
STOP_ID = "6f1e2d3c-0000-4000-8000-000000000003"

def order_json(order_id, client_order_id, side, order_type, status="accepted", filled="0", avg=None,
               stop=None, limit=None, legs=None, order_class="bracket"):
    """Return an order as Alpaca's API sends it (numbers are strings)"""
    return {"id": order_id, "client_order_id": client_order_id, "created_at": "2026-10-28T14:30:05Z",
            "updated_at": "2026-10-28T14:30:05Z", "submitted_at": "2026-10-28T14:30:05Z",
            "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415", "symbol": "AAPL", "asset_class": "us_equity",
            "qty": "10", "filled_qty": filled, "filled_avg_price": avg, "order_class": order_class,
            "order_type": order_type, "type": order_type, "side": side, "time_in_force": "day",
            "limit_price": limit, "stop_price": stop, "status": status, "extended_hours": False, "legs": legs}

def bracket_order(status="accepted", filled="0", avg=None):
    """Return an alpaca-py Order for a bracket buy with its two held legs"""
    legs = [order_json(TARGET_ID, "leg-target", "sell", "limit", status="held", limit="5.32"),
            order_json(STOP_ID, "leg-stop", "sell", "stop", status="held", stop="5.02")]
    return Order(**order_json(BUY_ID, "momentum-AAPL-buy-x", "buy", "market", status, filled, avg, legs=legs))

def api_error(status_code, message):
    """Return the APIError alpaca-py raises for an HTTP error answer"""
    response = requests.Response()
    response.status_code = status_code
    return APIError(json.dumps({"code": 40010001, "message": message}),
                    requests.HTTPError(response=response))

class FakeTradingClient:
    """Stands in for alpaca-py's TradingClient: records calls, returns or raises what it's given"""

    def __init__(self, answer=None, error=None, lookup_error=None, pages=()):
        self.answer = answer
        self.error = error
        self.lookup_error = lookup_error
        self.pages = list(pages)
        self.calls = []

    def _respond(self, error=None):
        if error is not None:
            raise error
        return self.answer

    def submit_order(self, request):
        self.calls.append(("submit_order", request.to_request_fields()))
        return self._respond(self.error)

    def get_order_by_client_id(self, client_order_id):
        self.calls.append(("get_order_by_client_id", client_order_id))
        return self._respond(self.lookup_error)

    def get_order_by_id(self, order_id, request=None):
        self.calls.append(("get_order_by_id", order_id, request.nested if request else None))
        return self._respond(self.error)

    def cancel_order_by_id(self, order_id):
        self.calls.append(("cancel_order_by_id", order_id))
        return self._respond(self.error)

    def get_account(self):
        self.calls.append(("get_account",))
        return self._respond(self.error)

    def get_all_positions(self):
        self.calls.append(("get_all_positions",))
        return self._respond(self.error)

    def get_all_assets(self, request=None):
        self.calls.append(("get_all_assets", request.to_request_fields() if request else None))
        return self._respond(self.error)

    def get(self, path, params):
        self.calls.append(("get", path, dict(params)))
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)

def submit_buy(broker):
    """Send the same bracket buy in every test"""
    return broker.submit_bracket_buy("momentum-AAPL-buy-x", "AAPL", 10, "day", Decimal("5.02"), Decimal("5.32"))

def test_bracket_buy_sends_market_buy_with_both_legs():
    """Send one bracket request with the stop, the target and the bot's ID"""
    client = FakeTradingClient(answer=bracket_order())

    submit_buy(AlpacaBroker(client))

    sent = client.calls[0][1]
    assert (sent["symbol"], sent["qty"], sent["side"], sent["type"], sent["time_in_force"], sent["order_class"]) == \
           ("AAPL", 10, "buy", "market", "day", "bracket")
    assert (sent["stop_loss"], sent["take_profit"], sent["client_order_id"]) == \
           ({"stop_price": 5.02}, {"limit_price": 5.32}, "momentum-AAPL-buy-x")

def test_bracket_buy_returns_plain_python_values():
    """Turn Alpaca's UUID, enums and number strings into str, int and Decimal"""

    order = submit_buy(AlpacaBroker(FakeTradingClient(answer=bracket_order())))

    assert (order.alpaca_order_id, order.client_order_id, order.side, order.order_type) == \
           (BUY_ID, "momentum-AAPL-buy-x", "buy", "market")
    assert (order.time_in_force, order.status, order.quantity, order.filled_quantity, order.filled_price) == \
           ("day", "accepted", 10, 0, None)

def test_filled_buy_keeps_fill_price_as_decimal():
    """Keep the average fill price exact"""

    order = submit_buy(AlpacaBroker(FakeTradingClient(answer=bracket_order("filled", "10", "5.1299"))))

    assert (order.status, order.filled_quantity, order.filled_price) == ("filled", 10, Decimal("5.1299"))

def test_bracket_buy_returns_both_legs_as_broker_orders():
    """Return the legs with their own IDs, held status and prices"""

    order = submit_buy(AlpacaBroker(FakeTradingClient(answer=bracket_order())))

    target, stop = order.legs
    assert all(isinstance(leg, BrokerOrder) for leg in order.legs)
    assert (target.alpaca_order_id, target.order_type, target.status, target.limit_price) == \
           (TARGET_ID, "limit", "held", Decimal("5.32"))
    assert (stop.alpaca_order_id, stop.order_type, stop.stop_price, stop.legs) == \
           (STOP_ID, "stop", Decimal("5.02"), ())

def test_market_sell_sends_a_plain_sell():
    """Send a sell with no bracket"""
    answer = Order(**order_json(BUY_ID, "momentum-AAPL-sell-x", "sell", "market", order_class="simple"))
    client = FakeTradingClient(answer=answer)

    order = AlpacaBroker(client).submit_market_sell("momentum-AAPL-sell-x", "AAPL", 10, "day")

    sent = client.calls[0][1]
    assert (sent["side"], sent["type"], sent["client_order_id"], "order_class" in sent) == \
           ("sell", "market", "momentum-AAPL-sell-x", False)
    assert (order.side, order.legs) == ("sell", ())

@pytest.mark.parametrize("error", [requests.exceptions.Timeout("read timed out"),
                                   requests.exceptions.ConnectionError("connection reset")])
def test_no_answer_is_unavailable(error):
    """Treat a timeout or a lost connection as 'may or may not exist'"""

    with pytest.raises(BrokerUnavailable):
        submit_buy(AlpacaBroker(FakeTradingClient(error=error)))

@pytest.mark.parametrize("status_code", [500, 502, 503, 504, 429])
def test_server_error_or_rate_limit_is_unavailable(status_code):
    """Treat Alpaca's server errors and a rate limit that outlasted alpaca-py's retries as unavailable"""

    with pytest.raises(BrokerUnavailable, match=str(status_code)):
        submit_buy(AlpacaBroker(FakeTradingClient(error=api_error(status_code, "try again"))))

def test_repeated_client_order_id_is_duplicate():
    """Recognise Alpaca refusing a client_order_id it already has"""

    with pytest.raises(DuplicateOrder):
        submit_buy(AlpacaBroker(FakeTradingClient(error=api_error(422, "client_order_id must be unique"))))

@pytest.mark.parametrize("status_code, message", [(403, "insufficient buying power"),
                                                  (422, "stop_price must be less than base_price"),
                                                  (400, "invalid qty")])
def test_other_client_errors_are_rejections(status_code, message):
    """Treat every other 4xx as a rejection, keeping Alpaca's message"""

    with pytest.raises(OrderRejected, match=message):
        submit_buy(AlpacaBroker(FakeTradingClient(error=api_error(status_code, message))))

def test_rejection_with_non_json_body_keeps_raw_text():
    """Keep the raw text when Alpaca's error body isn't JSON"""
    response = requests.Response()
    response.status_code = 403
    error = APIError("<html>forbidden</html>", requests.HTTPError(response=response))

    with pytest.raises(OrderRejected, match="forbidden"):
        submit_buy(AlpacaBroker(FakeTradingClient(error=error)))

def test_error_keeps_the_original_as_its_cause():
    """Keep alpaca-py's error attached for the logs"""
    original = api_error(403, "insufficient buying power")

    with pytest.raises(OrderRejected) as raised:
        submit_buy(AlpacaBroker(FakeTradingClient(error=original)))

    assert raised.value.__cause__ is original

def test_find_order_returns_the_order_with_its_legs():
    """Look up by the bot's ID, then fetch by Alpaca's ID with legs included"""
    client = FakeTradingClient(answer=bracket_order())

    order = AlpacaBroker(client).find_order("momentum-AAPL-buy-x")

    assert client.calls == [("get_order_by_client_id", "momentum-AAPL-buy-x"),
                            ("get_order_by_id", UUID(BUY_ID), True)]
    assert (order.alpaca_order_id, len(order.legs)) == (BUY_ID, 2)

def test_find_order_returns_none_when_alpaca_has_no_such_order():
    """Return None on Alpaca's 404 so the caller knows it's safe to send"""
    client = FakeTradingClient(lookup_error=api_error(404, "order not found"))

    assert AlpacaBroker(client).find_order("never-sent") is None

def test_find_order_raises_when_alpaca_cant_be_asked():
    """Never answer 'not found' when the lookup itself failed"""
    client = FakeTradingClient(lookup_error=requests.exceptions.Timeout("read timed out"))

    with pytest.raises(BrokerUnavailable):
        AlpacaBroker(client).find_order("momentum-AAPL-buy-x")

def test_get_order_looks_up_by_alpacas_id():
    """Look an order (or a single leg) up by Alpaca's ID, without its legs"""
    client = FakeTradingClient(answer=Order(**order_json(STOP_ID, "leg-stop", "sell", "stop", status="canceled",
                                                         stop="5.02", order_class="simple")))

    order = AlpacaBroker(client).get_order(STOP_ID)

    assert client.calls == [("get_order_by_id", STOP_ID, None)]
    assert (order.alpaca_order_id, order.status, order.stop_price) == (STOP_ID, "canceled", Decimal("5.02"))

def test_get_order_returns_none_when_alpaca_has_no_such_order():
    """Return None on Alpaca's 404"""
    client = FakeTradingClient(error=api_error(404, "order not found"))

    assert AlpacaBroker(client).get_order(STOP_ID) is None

def test_get_order_raises_when_alpaca_cant_be_asked():
    """Raise BrokerUnavailable when the lookup itself failed"""
    client = FakeTradingClient(error=requests.exceptions.Timeout("read timed out"))

    with pytest.raises(BrokerUnavailable, match="No answer"):
        AlpacaBroker(client).get_order(STOP_ID)

def activity(number):
    """Return a FILL activity with a distinct ID"""
    return {"id": f"20261030134220960::fill-{number}", "order_id": BUY_ID, "side": "buy", "qty": "1"}

def test_fill_activities_asks_for_fills_after_a_time_oldest_first():
    """Ask the FILL endpoint for fills after the time, oldest first"""
    client = FakeTradingClient(pages=[[activity(1)]])

    found = AlpacaBroker(client).get_fill_activities(datetime(2026, 10, 30, 17, 37, 20, 500000))

    assert client.calls == [("get", "/account/activities/FILL",
                             {"after": "2026-10-30T17:37:20Z", "direction": "asc", "page_size": 100})]
    assert found == [activity(1)]

def test_fill_activities_reads_every_page():
    """Ask for the next page from the last ID while a page comes back full"""
    full_page = [activity(n) for n in range(100)]
    client = FakeTradingClient(pages=[full_page, [activity(100)]])

    found = AlpacaBroker(client).get_fill_activities(datetime(2026, 10, 30))

    assert len(found) == 101
    assert client.calls[1][2]["page_token"] == "20261030134220960::fill-99"

def test_fill_activities_raise_when_alpaca_cant_be_asked():
    """Raise BrokerUnavailable on a server error"""
    client = FakeTradingClient(error=api_error(500, "internal error"))

    with pytest.raises(BrokerUnavailable, match="500"):
        AlpacaBroker(client).get_fill_activities(datetime(2026, 10, 30))

def test_cancel_order_sends_alpacas_id():
    """Cancel by Alpaca's order ID"""
    client = FakeTradingClient()

    AlpacaBroker(client).cancel_order(STOP_ID)

    assert client.calls == [("cancel_order_by_id", STOP_ID)]

def test_cancel_of_filled_order_is_rejected():
    """Report Alpaca refusing to cancel an order that already filled"""
    client = FakeTradingClient(error=api_error(422, "order is already in filled state"))

    with pytest.raises(OrderRejected, match="filled"):
        AlpacaBroker(client).cancel_order(STOP_ID)

class FakeResponse:
    """Just enough of a requests.Response for RateLimitedSession's logging"""
    status_code = 200
    url = "https://paper-api.alpaca.markets/v2/orders"
    headers = {}
    elapsed = timedelta(seconds=0.1)

    class request:
        method = "POST"

@pytest.fixture
def sent_kwargs(monkeypatch):
    """Capture the keyword arguments RateLimitedSession passes on to requests"""
    captured = {}

    def fake_request(self, method, url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return captured

def test_session_adds_default_timeout(sent_kwargs):
    """Give every Alpaca call a timeout, since alpaca-py passes none"""

    RateLimitedSession(RateLimiter()).request("POST", "https://paper-api.alpaca.markets/v2/orders")

    assert sent_kwargs["timeout"] == ALPACA_TIMEOUT_SECONDS

def test_session_keeps_callers_own_timeout(sent_kwargs):
    """Leave a timeout the caller chose alone"""

    RateLimitedSession(RateLimiter()).request("GET", "https://paper-api.alpaca.markets/v2/clock", timeout=3)

    assert sent_kwargs["timeout"] == 3

def account_json(equity="18345.99", last_equity="18400.00", buying_power="73383.96"):
    """Return an account as Alpaca's API sends it (numbers are strings)"""
    return {"id": "8f3c0f8e-0000-4000-8000-000000000001", "account_number": "PA1234", "status": "ACTIVE",
            "crypto_status": "ACTIVE", "currency": "USD", "buying_power": buying_power, "regt_buying_power": buying_power,
            "daytrading_buying_power": "0", "non_marginable_buying_power": equity, "cash": equity,
            "accrued_fees": "0", "portfolio_value": equity, "pattern_day_trader": False, "trading_blocked": False,
            "transfers_blocked": False, "account_blocked": False, "created_at": "2026-01-02T15:00:00Z",
            "trade_suspended_by_user": False, "multiplier": "4", "shorting_enabled": True, "equity": equity,
            "last_equity": last_equity, "long_market_value": "0", "short_market_value": "0", "initial_margin": "0",
            "maintenance_margin": "0", "last_maintenance_margin": "0", "sma": "0", "daytrade_count": 0}

def position_json(symbol, qty):
    """Return one position as Alpaca's API sends it"""
    return {"asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415", "symbol": symbol, "exchange": "NASDAQ",
            "asset_class": "us_equity", "avg_entry_price": "5.00", "qty": qty, "side": "long",
            "market_value": "50", "cost_basis": "50", "unrealized_pl": "0", "unrealized_plpc": "0",
            "unrealized_intraday_pl": "0", "unrealized_intraday_plpc": "0", "current_price": "5.00",
            "lastday_price": "5.00", "change_today": "0", "qty_available": qty}

def test_get_account_returns_equity_last_equity_and_buying_power():
    """Turn Alpaca's account numbers into Decimals"""
    client = FakeTradingClient(answer=TradeAccount(**account_json()))

    account = AlpacaBroker(client).get_account()

    assert (account.equity, account.last_equity, account.buying_power) ==            (Decimal("18345.99"), Decimal("18400.00"), Decimal("73383.96"))

def test_get_account_raises_when_alpaca_cant_be_asked():
    """Raise BrokerUnavailable on a timeout so risk skips buys this cycle"""
    client = FakeTradingClient(error=requests.exceptions.Timeout("read timed out"))

    with pytest.raises(BrokerUnavailable, match="No answer"):
        AlpacaBroker(client).get_account()

def test_get_positions_returns_shares_per_ticker():
    """Return every held ticker with its whole share count"""
    client = FakeTradingClient(answer=[Position(**position_json("AAPL", "10")), Position(**position_json("SPY", "1"))])

    positions = AlpacaBroker(client).get_positions()

    assert positions == {"AAPL": 10, "SPY": 1}

def test_get_positions_cuts_fractional_shares():
    """Cut 2.5 shares to 2, so a sell never asks for more than Alpaca holds"""
    client = FakeTradingClient(answer=[Position(**position_json("AAPL", "2.5"))])

    positions = AlpacaBroker(client).get_positions()

    assert positions == {"AAPL": 2}

def test_get_positions_is_empty_when_nothing_is_held():
    """Return an empty dict for a flat account"""

    positions = AlpacaBroker(FakeTradingClient(answer=[])).get_positions()

    assert positions == {}

def asset(symbol, tradable=True):
    """Build an alpaca-py Asset the way Alpaca's assets endpoint returns it"""
    return Asset(id=UUID("904837e3-3b76-47ec-b432-046db621571b"), **{"class": "us_equity"}, exchange="NASDAQ",
                 symbol=symbol, name=symbol, status="active", tradable=tradable, marginable=True, shortable=True,
                 easy_to_borrow=True, fractionable=True)

def test_get_tradable_tickers_returns_only_tradable_symbols():
    """Ask once for active US stocks and keep the ones Alpaca can trade"""
    client = FakeTradingClient(answer=[asset("AAPL"), asset("ZZZQ", tradable=False), asset("SPY")])

    tradable = AlpacaBroker(client).get_tradable_tickers()

    assert tradable == {"AAPL", "SPY"}
    assert client.calls == [("get_all_assets", {"status": "active", "asset_class": "us_equity"})]

def test_get_tradable_tickers_raises_when_alpaca_cant_be_asked():
    client = FakeTradingClient(error=requests.exceptions.Timeout("read timed out"))

    with pytest.raises(BrokerUnavailable):
        AlpacaBroker(client).get_tradable_tickers()

