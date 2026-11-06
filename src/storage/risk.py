"""
risk.py
Read what the risk snapshot needs from the database and save risk decisions
"""

#Standard Library
from datetime import date, datetime

#Local Imports
from logger import db_log

def get_strategy_rows(conn) -> list:
    """Return every strategy with its mode, the admin's budget and when that budget was last set

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"strategy_id", "strategy", "mode", "budget", "budget_set_at"}
    """
    rows = conn.cursor().execute(
        "SELECT strategy_id, strategy, mode, budget, budget_set_at FROM strategies ORDER BY strategy_id"
    ).fetchall()
    return [{"strategy_id": row.strategy_id, "strategy": row.strategy, "mode": row.mode, "budget": row.budget,
             "budget_set_at": row.budget_set_at} for row in rows]

def get_open_positions(conn) -> list:
    """Return every open position with the shares it still holds (buys minus sells)

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"position_id", "strategy_id", "ticker", "holding_type", "shares_held", "avg_entry_price"}
    """
    rows = conn.cursor().execute(
        "SELECT position_id, strategy_id, ticker, holding_type, shares_held, avg_entry_price "
        "FROM v_open_positions ORDER BY position_id"
    ).fetchall()
    return [{"position_id": row.position_id, "strategy_id": row.strategy_id, "ticker": row.ticker,
             "holding_type": row.holding_type, "shares_held": row.shares_held,
             "avg_entry_price": row.avg_entry_price} for row in rows]

def get_exits_since(conn, since: datetime) -> list:
    """Return the positions closed since a time, for cooldowns

    Parameters:
        conn (Connection): An open database connection
        since (datetime): Naive UTC, e.g. the start of today in New York

    Returns:
        A list of {"strategy_id", "ticker", "exit_reason", "closed_at"}
    """
    rows = conn.cursor().execute(
        "SELECT p.strategy_id, t.ticker, p.exit_reason, p.closed_at "
        "FROM positions p JOIN tickers t ON t.ticker_id = p.ticker_id "
        "WHERE p.[status] = 'closed' AND p.closed_at >= ? "
        "ORDER BY p.closed_at",
        (since,),
    ).fetchall()
    return [{"strategy_id": row.strategy_id, "ticker": row.ticker, "exit_reason": row.exit_reason,
             "closed_at": row.closed_at} for row in rows]

def get_daily_pnl(conn, trade_date: date) -> dict:
    """Return each strategy's realized P/L on one New York trading day, per holding type

    Parameters:
        conn (Connection): An open database connection
        trade_date (date): The New York date

    Returns:
        {(strategy_id, holding_type): realized P/L as a Decimal}; a strategy that closed nothing isn't in it
    """
    rows = conn.cursor().execute(
        "SELECT strategy_id, holding_type, realized_pnl FROM v_strategy_daily_pnl WHERE trade_date_et = ?",
        (trade_date,),
    ).fetchall()
    return {(row.strategy_id, row.holding_type): row.realized_pnl for row in rows}

def get_pnl_since_budget(conn) -> dict:
    """Return each strategy's realized P/L since its budget was last set, and the highest it reached

    The running total adds positions in the order they closed; its highest point is the peak the
    drawdown limit measures from.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {strategy_id: {"total": Decimal, "peak": Decimal}}; a strategy with no closed position since is left out
    """
    rows = conn.cursor().execute(
        "WITH closed AS ("
        "    SELECT p.strategy_id, p.realized_pnl, "
        "           SUM(p.realized_pnl) OVER (PARTITION BY p.strategy_id ORDER BY p.closed_at, p.position_id "
        "                                     ROWS UNBOUNDED PRECEDING) AS running_pnl "
        "    FROM positions p "
        "    JOIN strategies s ON s.strategy_id = p.strategy_id "
        "    WHERE p.[status] = 'closed' AND p.closed_at >= s.budget_set_at"
        ") "
        "SELECT strategy_id, SUM(realized_pnl) AS total_pnl, MAX(running_pnl) AS peak_pnl "
        "FROM closed GROUP BY strategy_id"
    ).fetchall()
    return {row.strategy_id: {"total": row.total_pnl, "peak": row.peak_pnl} for row in rows}

def get_events_since(conn, event_types: tuple, since: datetime) -> set:
    """Return which of these bot_events happened since a time, and for which strategy

    Parameters:
        conn (Connection): An open database connection
        event_types (tuple): The event_type values to look for
        since (datetime): Naive UTC

    Returns:
        A set of (event_type, strategy_id); strategy_id is None for an account-wide event
    """
    placeholders = ", ".join("?" * len(event_types))
    rows = conn.cursor().execute(
        f"SELECT DISTINCT event_type, strategy_id FROM bot_events "
        f"WHERE event_type IN ({placeholders}) AND occurred_at >= ?",
        (*event_types, since),
    ).fetchall()
    return {(row.event_type, row.strategy_id) for row in rows}

def get_events_since_budget_set(conn, event_type: str) -> set:
    """Return the strategies with this event since their budget was last set

    Parameters:
        conn (Connection): An open database connection
        event_type (str): The event_type to look for, e.g. "drawdown_limit"

    Returns:
        A set of strategy_ids
    """
    rows = conn.cursor().execute(
        "SELECT DISTINCT e.strategy_id FROM bot_events e "
        "JOIN strategies s ON s.strategy_id = e.strategy_id "
        "WHERE e.event_type = ? AND e.occurred_at >= s.budget_set_at",
        (event_type,),
    ).fetchall()
    return {row.strategy_id for row in rows}

def get_latest_events(conn, event_types: tuple) -> dict:
    """Return the newest of these bot_events for each strategy, e.g. whether "budget_full" or "budget_room" came last

    Parameters:
        conn (Connection): An open database connection
        event_types (tuple): The event_type values that take turns, e.g. ("budget_full", "budget_room")

    Returns:
        {strategy_id: event_type}; strategy_id is None for account-wide events
    """
    placeholders = ", ".join("?" * len(event_types))
    rows = conn.cursor().execute(
        f"WITH ranked AS ("
        f"    SELECT event_type, strategy_id, "
        f"           ROW_NUMBER() OVER (PARTITION BY strategy_id ORDER BY occurred_at DESC, bot_event_id DESC) AS newest "
        f"    FROM bot_events WHERE event_type IN ({placeholders})"
        f") "
        f"SELECT event_type, strategy_id FROM ranked WHERE newest = 1",
        event_types,
    ).fetchall()
    return {row.strategy_id: row.event_type for row in rows}

def get_previous_parameters(conn, before: datetime) -> dict:
    """Return the last value each strategy used for each risk parameter before a time, for the rate limit

    Parameters:
        conn (Connection): An open database connection
        before (datetime): Naive UTC, the start of today in New York

    Returns:
        {(strategy_id, name): used value as a float}
    """
    rows = conn.cursor().execute(
        "WITH ranked AS ("
        "    SELECT s.strategy_id, rp.[name], rp.used, "
        "           ROW_NUMBER() OVER (PARTITION BY s.strategy_id, rp.[name] "
        "                              ORDER BY s.generated_at DESC, rp.risk_decision_parameter_id DESC) AS newest "
        "    FROM risk_decision_parameters rp "
        "    JOIN risk_decisions rd ON rd.risk_decision_id = rp.risk_decision_id "
        "    JOIN signals s ON s.signal_id = rd.signal_id "
        "    WHERE s.generated_at < ?"
        ") "
        "SELECT strategy_id, [name], used FROM ranked WHERE newest = 1",
        (before,),
    ).fetchall()
    return {(row.strategy_id, row.name): row.used for row in rows}

def insert_risk_decision(conn, signal_id: int, *, sizer: str, sized_quantity: int, equity: float,
                         buying_power: float, trading_budget: float, account_exposure: float,
                         strategy_exposure: float, ticker_exposure: float, open_positions: int, shares_held: int,
                         broker_shares: int, strategy_daily_pnl: float, strategy_drawdown: float,
                         account_daily_change: float, start_equity: float) -> int:
    """Save what risk knew when it decided one signal and return the risk_decision_id

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        signal_id (int): The signal decided
        sizer (str): The sizer's "name:version"
        sized_quantity (int): What the sizer wanted before the guardrails
        equity (float): Equity risk used (capped)
        buying_power (float): Alpaca's buying power
        trading_budget (float): The budget the strategy sized from
        account_exposure (float): Money in every open position, at entry prices
        strategy_exposure (float): Money in this strategy's open positions
        ticker_exposure (float): Money in this ticker across every strategy
        open_positions (int): Open positions in the account
        shares_held (int): Shares of the ticker this strategy holds
        broker_shares (int): Shares of the ticker Alpaca holds
        strategy_daily_pnl (float): The strategy's realized P/L today, for the signal's holding type
        strategy_drawdown (float): How far the strategy is below its peak (0 or more)
        account_daily_change (float): equity - last_equity at Alpaca
        start_equity (float): The capped equity at yesterday's close, the kill switch's base

    Returns:
        The new risk_decision_id
    """
    row = conn.cursor().execute(
        "INSERT INTO risk_decisions (signal_id, sizer, sized_quantity, equity, buying_power, trading_budget, "
        "account_exposure, strategy_exposure, ticker_exposure, open_positions, shares_held, broker_shares, "
        "strategy_daily_pnl, strategy_drawdown, account_daily_change, start_equity) "
        "OUTPUT INSERTED.risk_decision_id "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (signal_id, sizer, sized_quantity, equity, buying_power, trading_budget, account_exposure,
         strategy_exposure, ticker_exposure, open_positions, shares_held, broker_shares, strategy_daily_pnl,
         strategy_drawdown, account_daily_change, start_equity),
    ).fetchone()
    db_log.debug(f"risk_decisions saved: signal_id {signal_id}, risk_decision_id {row[0]}")
    return row[0]

def insert_risk_decision_parameter(conn, risk_decision_id: int, *, name: str, provider: str, proposed: float | None,
                                   used: float, clamped: bool, rate_limited: bool, fell_back: bool):
    """Save one parameter a risk decision used: what the provider proposed and what was used

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        risk_decision_id (int): The decision it belongs to
        name (str): The parameter, e.g. "position_fraction"
        provider (str): The provider's "name:version"
        proposed (float | None): The provider's value; None if it gave nothing usable
        used (float): The value used after the bounds
        clamped (bool): True if the min / max changed it
        rate_limited (bool): True if the daily change limit changed it
        fell_back (bool): True if the static value replaced a failed provider
    """
    conn.cursor().execute(
        "INSERT INTO risk_decision_parameters (risk_decision_id, [name], [provider], proposed, used, clamped, "
        "rate_limited, fell_back) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (risk_decision_id, name, provider, proposed, used, clamped, rate_limited, fell_back),
    )
