"""
strategies.py
Read and write the strategies table
"""

#Third Party Libraries
from pyodbc import IntegrityError

#Local Imports
from logger import db_log
from storage.connections import is_duplicate_error

def register_strategy(conn, name: str, time_frame: str, holding_type: str) -> bool:
    """Insert a new strategy, switched off and with no budget

    is_active and budget are both set to 0 on purpose, so a new strategy can't trade until
    the admin switches it on and funds it. A name that's already registered is skipped.
    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        name (str): The strategy's NAME
        time_frame (str): The strategy's TIME_FRAME, e.g. "15Min"
        holding_type (str): The strategy's DEFAULT_HOLDING_TYPE, "day" or "swing"

    Returns:
        True if inserted, False if the name was already registered

    Raises:
        pyodbc.IntegrityError for any database error other than a duplicate
    """
    try:
        conn.cursor().execute(
            "INSERT INTO strategies (strategy, time_frame, default_holding_type, budget, is_active) "
            "VALUES (?, ?, ?, 0, 0)",
            (name, time_frame, holding_type),
        )
    except IntegrityError as e:
        if is_duplicate_error(e):
            db_log.info(f"Strategy {name} is already registered")
            return False
        raise
    db_log.info(f"Registered strategy {name} ({time_frame}, {holding_type}): inactive, budget 0")
    return True

def get_strategy_rows(conn) -> dict:
    """Return every strategies row, active or not, by name

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {name: {"strategy_id", "time_frame", "default_holding_type", "budget", "is_active"}}
    """
    cursor = conn.cursor()
    cursor.execute("SELECT strategy_id, strategy, time_frame, default_holding_type, budget, is_active "
                   "FROM strategies")
    return {row.strategy: {"strategy_id": row.strategy_id, "time_frame": row.time_frame,
                           "default_holding_type": row.default_holding_type, "budget": row.budget,
                           "is_active": bool(row.is_active)}
            for row in cursor.fetchall()}

def get_active_strategies(conn) -> list:
    """Return the strategies the admin has switched on

    Called every cycle, so switching a strategy on or off needs no restart.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"strategy_id", "strategy", "time_frame", "default_holding_type", "budget"},
        ordered by name
    """
    cursor = conn.cursor()
    cursor.execute("SELECT strategy_id, strategy, time_frame, default_holding_type, budget "
                   "FROM strategies WHERE is_active = 1 ORDER BY strategy")
    return [{"strategy_id": row.strategy_id, "strategy": row.strategy, "time_frame": row.time_frame,
             "default_holding_type": row.default_holding_type, "budget": row.budget}
            for row in cursor.fetchall()]

def count_open_positions(conn, strategy_id: int) -> int:
    """Return how many open positions a strategy holds

    Parameters:
        conn (Connection): An open database connection
        strategy_id (int): The strategy's id

    Returns:
        The number of open positions as an int
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM v_open_positions WHERE strategy_id = ?", (strategy_id,))
    return cursor.fetchone()[0]
