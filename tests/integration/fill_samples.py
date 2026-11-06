"""
fill_samples.py
Shared sample orders and Alpaca messages for the fill stream's integration tests
"""

#Standard Library
import copy
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

#Local Imports
from execution.orders import LEG_EXIT_REASONS
from fills.events import from_stream
from storage.orders import insert_order
from storage.watchlist import get_or_create_ticker

PAPER_RUN = json.loads((Path(__file__).parent.parent / "fixtures" / "stream_events_paper.json").read_text("utf-8"))
PAPER_FILL = next(m for m in PAPER_RUN["stream"] if m["event"] == "fill" and m["order"]["side"] == "buy")
SUBMITTED_AT = datetime(2026, 11, 2, 14, 31)
FILLED_AT = datetime(2026, 11, 2, 14, 31, 4)
NOW = datetime(2026, 11, 2, 15, 0)

class CommitCounter:
    """Wraps the test connection: counts commits and rollbacks instead of making them, so each test still rolls back"""

    def __init__(self, conn):
        self._conn = conn
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def __getattr__(self, name):
        return getattr(self._conn, name)

def add_strategy(conn, name="momentum", time_frame="15Min", holding_type="day") -> int:
    """Register a strategy and return its id"""
    return conn.execute("INSERT INTO strategies (strategy, time_frame, default_holding_type, budget, mode) "
                        "OUTPUT INSERTED.strategy_id VALUES (?, ?, ?, 1000, 'live')",
                        (name, time_frame, holding_type)).fetchone()[0]

def ticker_id(conn, ticker="AAPL") -> int:
    return get_or_create_ticker(conn, ticker, date(2026, 11, 2))

def add_bracket(conn, strategy_id, number=1, quantity=10, legs=True) -> dict:
    """Save a bracket buy the way E1 does (buy row, then its two held legs) and return their order_ids"""
    ids = {"buy": insert_order(conn, client_order_id=f"momentum-AAPL-buy-{number}",
                               alpaca_order_id=f"alpaca-buy-{number}", side="buy", quantity=quantity,
                               order_type="market", time_in_force="day", submitted_at=SUBMITTED_AT,
                               status="accepted", strategy_id=strategy_id, ticker_id=ticker_id(conn),
                               request_price=Decimal("5.00"))}
    if legs:
        add_legs(conn, strategy_id, ids["buy"], number, quantity)
        ids.update(leg_ids(conn, ids["buy"]))
    return ids

def add_legs(conn, strategy_id, buy_id, number=1, quantity=10):
    """Save a buy's target and stop legs, as E1 does after Alpaca answers"""
    for order_type, price in (("limit", Decimal("5.20")), ("stop", Decimal("4.90"))):
        insert_order(conn, client_order_id=f"leg-{order_type}-{number}", alpaca_order_id=f"alpaca-{order_type}-{number}",
                     side="sell", quantity=quantity, order_type=order_type, time_in_force="day",
                     submitted_at=SUBMITTED_AT, status="held", strategy_id=strategy_id, ticker_id=ticker_id(conn),
                     request_price=price, parent_order_id=buy_id, exit_reason=LEG_EXIT_REASONS[order_type])

def leg_ids(conn, buy_id) -> dict:
    rows = conn.execute("SELECT order_id, order_type FROM orders WHERE parent_order_id = ?", buy_id).fetchall()
    return {"target" if row.order_type == "limit" else "stop": row.order_id for row in rows}

def add_sell(conn, strategy_id, position_id, number=1, quantity=10, exit_reason="end_of_day") -> int:
    """Save a plain market sell the way E3 will, linked to the position it closes"""
    return insert_order(conn, client_order_id=f"momentum-AAPL-sell-{number}", alpaca_order_id=f"alpaca-sell-{number}",
                        side="sell", quantity=quantity, order_type="market", time_in_force="day",
                        submitted_at=SUBMITTED_AT, status="accepted", strategy_id=strategy_id,
                        ticker_id=ticker_id(conn), request_price=Decimal("5.00"), position_id=position_id,
                        exit_reason=exit_reason)

def message(event, alpaca_order_id, *, client_order_id=None, side="buy", order_type="market", status=None,
            quantity=10, filled=0, average=None, execution_id=None, fill_quantity=None, price=None,
            at="2026-11-02T14:31:04Z", ticker="AAPL") -> dict:
    """Return a stream message shaped like the real paper one, with the given values"""
    data = copy.deepcopy(PAPER_FILL)
    data.update({"event": event, "timestamp": at, "execution_id": execution_id,
                 "qty": None if fill_quantity is None else str(fill_quantity),
                 "price": None if price is None else str(price)})
    data["order"].update({"id": alpaca_order_id, "client_order_id": client_order_id or f"coid-{alpaca_order_id}",
                          "symbol": ticker, "side": side, "order_type": order_type, "type": order_type,
                          "status": status or event, "qty": str(quantity), "filled_qty": str(filled),
                          "filled_avg_price": None if average is None else str(average)})
    return data

def fill(alpaca_order_id, fill_quantity, price, execution_id, *, filled=None, average=None, status=None,
         side="buy", order_type="market", quantity=10, event=None, **extra):
    """Return a fill TradeUpdate; a full fill unless filled says how many of quantity are filled so far"""
    filled = fill_quantity if filled is None else filled
    event = event or ("fill" if filled == quantity else "partial_fill")
    status = status or ("filled" if filled == quantity else "partially_filled")
    return from_stream(message(event, alpaca_order_id, side=side, order_type=order_type, status=status,
                               quantity=quantity, filled=filled, average=average or price, execution_id=execution_id,
                               fill_quantity=fill_quantity, price=price, **extra))

def status_event(event, alpaca_order_id, *, side="sell", order_type="stop", status=None, **extra):
    """Return a non-fill TradeUpdate, e.g. a leg going new or canceled"""
    return from_stream(message(event, alpaca_order_id, side=side, order_type=order_type, status=status,
                               execution_id="not-a-fill-id", **extra))

def order(conn, order_id):
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", order_id).fetchone()

def positions(conn):
    return conn.execute("SELECT * FROM positions ORDER BY position_id").fetchall()

def trades(conn):
    return conn.execute("SELECT * FROM trades ORDER BY trade_id").fetchall()
