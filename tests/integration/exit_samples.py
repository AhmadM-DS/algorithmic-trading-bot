"""
exit_samples.py
Shared sample bracket positions, a calendar and a fake broker that keeps each order's state, for the E3 tests
"""

#Standard Library
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

#Third Party Libraries
import pandas as pd

#Local Imports
from execution.broker import BrokerOrder, BrokerUnavailable, OrderRejected
from storage.exits import get_open_position
from storage.fills import FINAL_STATUSES, insert_position, insert_trade, update_order_from_broker
from storage.orders import insert_order
from storage.watchlist import get_or_create_ticker

TODAY = date(2026, 11, 9)
OPEN = datetime(2026, 11, 9, 14, 30)
CLOSE = datetime(2026, 11, 9, 21, 0)
MIDDAY = datetime(2026, 11, 9, 17, 0)
CALENDAR = {
    date(2026, 11, 6): {"open": pd.Timestamp("2026-11-06 14:30", tz="UTC"),
                        "close": pd.Timestamp("2026-11-06 21:00", tz="UTC")},
    TODAY: {"open": pd.Timestamp("2026-11-09 14:30", tz="UTC"), "close": pd.Timestamp("2026-11-09 21:00", tz="UTC")},
}
"""Friday Nov 6 and Monday Nov 9, 2026 (9:30-16:00 New York)"""

class CommitCounter:
    """Wraps the test connection: counts commits instead of making them, so each test still rolls back"""

    def __init__(self, conn):
        self._conn = conn
        self.commits = 0

    def commit(self):
        self.commits += 1

    def __getattr__(self, name):
        return getattr(self._conn, name)

class FakeExitBroker:
    """Stands in for AlpacaBroker: keeps each order's state, cancels it, and plays scripted answers to get_order

    polls maps an Alpaca ID to the answers its get_order calls return after a cancel, one per call, the last one
    repeating; an order with no script just becomes canceled.
    """

    def __init__(self, orders=(), positions=None, polls=None, cancel_error=None, positions_error=None,
                 sell_error=None):
        self.orders = {order.alpaca_order_id: order for order in orders}
        self.positions = dict(positions or {})
        self.polls = {alpaca_order_id: list(answers) for alpaca_order_id, answers in (polls or {}).items()}
        self.cancel_error = cancel_error
        self.positions_error = positions_error
        self.sell_error = sell_error
        self.calls = []

    def cancel_order(self, alpaca_order_id):
        self.calls.append(("cancel", alpaca_order_id))
        if self.cancel_error is not None:
            raise self.cancel_error
        order = self.orders[alpaca_order_id]
        if order.status in FINAL_STATUSES:
            raise OrderRejected(f"order is not cancelable (status {order.status})")
        if alpaca_order_id not in self.polls:
            self.orders[alpaca_order_id] = replace(order, status="canceled")

    def get_order(self, alpaca_order_id):
        self.calls.append(("get", alpaca_order_id))
        script = self.polls.get(alpaca_order_id)
        if script:
            self.orders[alpaca_order_id] = script.pop(0) if len(script) > 1 else script[0]
        return self.orders.get(alpaca_order_id)

    def get_positions(self):
        self.calls.append(("positions",))
        if self.positions_error is not None:
            raise self.positions_error
        return dict(self.positions)

    def submit_market_sell(self, client_order_id, ticker, quantity, time_in_force):
        self.calls.append(("sell", ticker, quantity, time_in_force))
        if self.sell_error is not None:
            raise self.sell_error
        return BrokerOrder(f"alpaca-{client_order_id}", client_order_id, "sell", "market", time_in_force, "accepted",
                           quantity, 0, None, None, None)

    def find_order(self, client_order_id):
        return None

    def sells(self):
        """Return the (ticker, quantity) of every sell sent"""
        return [(call[1], call[2]) for call in self.calls if call[0] == "sell"]

def alpaca_unavailable():
    return BrokerUnavailable("No answer from Alpaca: read timed out")

def add_strategy(conn, name="momentum", holding_type="day") -> int:
    """Register a strategy and return its id"""
    return conn.execute("INSERT INTO strategies (strategy, time_frame, default_holding_type, budget, mode) "
                        "OUTPUT INSERTED.strategy_id VALUES (?, '15Min', ?, 250, 'live')",
                        (name, holding_type)).fetchone()[0]

def strategy_id(conn, name) -> int:
    return conn.execute("SELECT strategy_id FROM strategies WHERE strategy = ?", name).fetchone()[0]

def ticker_id(conn, ticker="AAPL") -> int:
    return get_or_create_ticker(conn, ticker, TODAY)

def bracket_position(conn, strategy, ticker="AAPL", shares=10, number=1, opened_at=OPEN, holding_type="day",
                     price="5.00") -> dict:
    """Save a filled bracket buy, its held stop and open target, and the position it opened

    Returns:
        {"position": the open position dict, "orders": the three BrokerOrders as Alpaca has them}
    """
    tid = ticker_id(conn, ticker)
    position_id = insert_position(conn, strategy_id=strategy, ticker_id=tid, signal_id=None, time_frame="15Min",
                                  holding_type=holding_type, opened_at=opened_at, quantity=shares,
                                  price=Decimal(price))
    tif = "day" if holding_type == "day" else "gtc"
    common = {"time_in_force": tif, "submitted_at": opened_at, "strategy_id": strategy, "ticker_id": tid,
              "position_id": position_id}
    buy_id = insert_order(conn, client_order_id=f"exit-{number}-buy", alpaca_order_id=f"buy-{number}", side="buy",
                          quantity=shares, order_type="market", status="filled", **common)
    update_order_from_broker(conn, buy_id, f"buy-{number}", "filled", shares, Decimal(price))
    insert_order(conn, client_order_id=f"exit-{number}-stop", alpaca_order_id=f"stop-{number}", side="sell",
                 quantity=shares, order_type="stop", status="held", parent_order_id=buy_id, exit_reason="stop_loss",
                 request_price=Decimal(price) - Decimal("0.10"), **common)
    insert_order(conn, client_order_id=f"exit-{number}-target", alpaca_order_id=f"target-{number}", side="sell",
                 quantity=shares, order_type="limit", status="new", parent_order_id=buy_id,
                 exit_reason="take_profit", request_price=Decimal(price) + Decimal("0.20"), **common)
    insert_trade(conn, fill_id=f"exit-fill-{number}", side="buy", quantity=shares, filled_at=opened_at,
                 fill_price=Decimal(price), time_frame="15Min", exit_reason=None, position_id=position_id,
                 order_id=buy_id)
    orders = (
        BrokerOrder(f"buy-{number}", f"exit-{number}-buy", "buy", "market", tif, "filled", shares, shares,
                    Decimal(price), None, None),
        BrokerOrder(f"stop-{number}", f"exit-{number}-stop", "sell", "stop", tif, "held", shares, 0, None,
                    Decimal(price) - Decimal("0.10"), None),
        BrokerOrder(f"target-{number}", f"exit-{number}-target", "sell", "limit", tif, "new", shares, 0, None, None,
                    Decimal(price) + Decimal("0.20")),
    )
    return {"position": get_open_position(conn, position_id), "orders": orders}

def leg(sample, kind, status, filled=0) -> BrokerOrder:
    """Return a sample's stop or target leg as Alpaca would answer it now"""
    order = next(o for o in sample["orders"] if o.alpaca_order_id.startswith(kind))
    return replace(order, status=status, filled_quantity=filled)

def order_rows(conn, position_id) -> list:
    """Return every order of a position, oldest first"""
    return conn.execute("SELECT * FROM orders WHERE position_id = ? ORDER BY order_id", position_id).fetchall()

def sell_rows(conn, position_id) -> list:
    """Return a position's sells that aren't bracket legs, oldest first"""
    return conn.execute("SELECT * FROM orders WHERE position_id = ? AND side = 'sell' AND parent_order_id IS NULL "
                        "ORDER BY order_id", position_id).fetchall()
