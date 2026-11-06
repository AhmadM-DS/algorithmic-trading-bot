"""
risk_samples.py
Shared sample strategies, positions, bot_events and a fake broker for the risk state integration tests
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

#Local Imports
from execution.broker import BrokerAccount, BrokerUnavailable
from storage.fills import close_position, insert_position, insert_trade
from storage.orders import insert_order
from storage.risk import insert_risk_decision, insert_risk_decision_parameter
from storage.watchlist import get_or_create_ticker

class FakeBroker:
    """Stands in for AlpacaBroker: returns the account and positions it was built with, or raises"""

    def __init__(self, equity="1000", last_equity="1000", buying_power="4000", positions=None, error=False):
        self.account = BrokerAccount(Decimal(equity), Decimal(last_equity), Decimal(buying_power))
        self.positions = positions or {}
        self.error = error

    def get_account(self):
        if self.error:
            raise BrokerUnavailable("No answer from Alpaca: read timed out")
        return self.account

    def get_positions(self):
        return self.positions

def db_now(conn) -> datetime:
    """Return the database's UTC time, naive, so rows line up with the defaults it fills in"""
    return conn.execute("SELECT SYSUTCDATETIME()").fetchone()[0]

def aware(value: datetime) -> datetime:
    """Return a naive UTC time as timezone-aware, as build_context takes it"""
    return value.replace(tzinfo=timezone.utc)

def as_admin(conn, sql, params=()):
    """Run one statement as the admin (the bot can't change strategies), then switch back to the bot"""
    conn.execute("REVERT;")
    conn.execute(sql, params)
    conn.execute("EXECUTE AS USER = 'test_bot';")

def add_strategy(conn, name="momentum", budget=250, mode="live") -> int:
    """Register a strategy and return its id; its budget_set_at is the database's now"""
    return conn.execute("INSERT INTO strategies (strategy, time_frame, default_holding_type, budget, mode) "
                        "OUTPUT INSERTED.strategy_id VALUES (?, '15Min', 'day', ?, ?)",
                        (name, budget, mode)).fetchone()[0]

def ticker_id(conn, ticker="AAPL") -> int:
    return get_or_create_ticker(conn, ticker, date(2026, 11, 6))

def closed_position(conn, strategy_id, pnl, closed_at, exit_reason="signal", ticker="AAPL", holding_type="day") -> int:
    """Save a position that closed at closed_at with this realized P/L and return its id"""
    position_id = insert_position(conn, strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker), signal_id=None,
                                  time_frame="15Min", holding_type=holding_type,
                                  opened_at=closed_at - timedelta(minutes=10), quantity=1, price=Decimal("10"))
    close_position(conn, position_id, closed_at, exit_reason, Decimal(str(pnl)))
    return position_id

def open_position(conn, strategy_id, shares=5, price="10", ticker="AAPL", number=1) -> int:
    """Save an open position with one buy fill and return its id"""
    opened_at = db_now(conn)
    position_id = insert_position(conn, strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker), signal_id=None,
                                  time_frame="15Min", holding_type="day", opened_at=opened_at, quantity=shares,
                                  price=Decimal(price))
    order_id = insert_order(conn, client_order_id=f"risk-{strategy_id}-{ticker}-{number}", side="buy",
                            quantity=shares, order_type="market", time_in_force="day", submitted_at=opened_at,
                            status="filled", strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker),
                            position_id=position_id)
    insert_trade(conn, fill_id=f"fill-{strategy_id}-{ticker}-{number}", side="buy", quantity=shares,
                 filled_at=opened_at, fill_price=Decimal(price), time_frame="15Min", exit_reason=None,
                 position_id=position_id, order_id=order_id)
    return position_id

def add_event(conn, event_type, strategy_id=None, occurred_at=None):
    """Save one bot_events row, at the database's now unless occurred_at is given"""
    if occurred_at is None:
        conn.execute("INSERT INTO bot_events (event_type, strategy_id) VALUES (?, ?)", (event_type, strategy_id))
    else:
        conn.execute("INSERT INTO bot_events (event_type, strategy_id, occurred_at) VALUES (?, ?, ?)",
                     (event_type, strategy_id, occurred_at))

def events(conn, event_type):
    """Return every bot_events row of one type, oldest first"""
    return conn.execute("SELECT * FROM bot_events WHERE event_type = ? ORDER BY bot_event_id", event_type).fetchall()

def add_signal(conn, strategy_id, generated_at, ticker="AAPL") -> int:
    """Save a taken buy signal and return its id"""
    return conn.execute(
        "INSERT INTO signals (side, time_frame, holding_type, quantity, reason, generated_at, taken, [source], "
        "strategy_version, git_commit, market_data_plan, data_feed, strategy_id, ticker_id) "
        "OUTPUT INSERTED.signal_id "
        "VALUES ('buy', '15Min', 'day', 5, 'test', ?, 1, 'live', '1.0.0', 'abc123', 'delayed', 'sip', ?, ?)",
        (generated_at, strategy_id, ticker_id(conn, ticker)),
    ).fetchone()[0]

def add_used_parameter(conn, strategy_id, name, used, generated_at):
    """Save a decided signal that used this parameter value"""
    decision_id = insert_risk_decision(
        conn, add_signal(conn, strategy_id, generated_at), sizer="fixed_budget:1.0.0", sized_quantity=5,
        equity=1000, buying_power=4000, trading_budget=250, account_exposure=0, strategy_exposure=0,
        ticker_exposure=0, open_positions=0, shares_held=0, broker_shares=0, strategy_daily_pnl=0,
        strategy_drawdown=0, account_daily_change=0, start_equity=1000)
    insert_risk_decision_parameter(conn, decision_id, name=name, provider="static:1.0.0", proposed=used, used=used,
                                   clamped=False, rate_limited=False, fell_back=False)
