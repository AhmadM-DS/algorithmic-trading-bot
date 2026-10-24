"""
registry.py
Check every strategy at startup, register new ones and match each with its strategies row
"""

#Local Imports
from config.constants import DISCORD_MENTION
from logger import health_log
from storage.events import insert_bot_event
from storage.strategies import count_open_positions, get_strategy_rows, register_strategy

STRATEGY_SKIPPED = "strategy_skipped"

def compare_with_row(strategy, row: dict) -> list:
    """Return every difference between a strategy's settings and its strategies row

    Parameters:
        strategy (Strategy): A strategy that passed check_settings
        row (dict): Its row from get_strategy_rows

    Returns:
        A list of readable differences, empty when they match
    """
    differences = []
    if strategy.TIME_FRAME != row["time_frame"]:
        differences.append(f"TIME_FRAME is {strategy.TIME_FRAME!r} in the class "
                           f"but {row['time_frame']!r} in the strategies table")
    if strategy.DEFAULT_HOLDING_TYPE != row["default_holding_type"]:
        differences.append(f"DEFAULT_HOLDING_TYPE is {strategy.DEFAULT_HOLDING_TYPE!r} in the class "
                           f"but {row['default_holding_type']!r} in the strategies table")
    return differences

def _skip(conn, name: str, reason: str, row: dict | None) -> dict:
    """Log a skipped strategy, save its strategy_skipped event and return what the alert needs"""
    strategy_id = row["strategy_id"] if row else None
    open_positions = count_open_positions(conn, strategy_id) if row else 0
    insert_bot_event(conn, STRATEGY_SKIPPED, details=f"{name}: {reason}", strategy_id=strategy_id)
    health_log.warning(f"Skipped strategy {name}: {reason}")
    return {"name": name, "reason": reason, "open_positions": open_positions}

def load_strategies(conn, strategies: list, profile: dict) -> tuple:
    """Return the strategies that can run and every one that has to sit out

    Parameters:
        conn (Connection): An open database connection
        strategies (list): One instance of every strategy class
        profile (dict): The market data profile from get_market_data_profile

    Returns:
        (runnable, skipped). runnable = {name: strategy} for every strategy that passed,
        in any mode: an off strategy still runs its sells, and changing a mode needs no
        restart. skipped = a list of {"name", "reason", "open_positions"}.
    """
    rows = get_strategy_rows(conn)
    names = [strategy.NAME for strategy in strategies]
    runnable = {}
    skipped = []

    for strategy in strategies:
        name = strategy.NAME or type(strategy).__name__
        row = rows.get(strategy.NAME)
        try:
            strategy.check_settings(profile)
        except ValueError as error:
            skipped.append(_skip(conn, name, str(error), row))
            continue
        if names.count(name) > 1:
            classes = [type(other).__name__ for other in strategies if other.NAME == name]
            skipped.append(_skip(conn, name, f"NAME {name!r} is used by more than one strategy class "
                                             f"({', '.join(classes)})", row))
            continue
        if row is None:
            register_strategy(conn, name, strategy.TIME_FRAME, strategy.DEFAULT_HOLDING_TYPE)
            health_log.info(f"New strategy {name} registered in shadow mode: set it to live and give it a budget to trade")
        else:
            differences = compare_with_row(strategy, row)
            if differences:
                skipped.append(_skip(conn, name, "; ".join(differences), row))
                continue
        runnable[name] = strategy

    for name, row in rows.items():
        if row["mode"] != "off" and name not in names:
            skipped.append(_skip(conn, name, f"is in {row['mode']} mode in the strategies table "
                                             "but no strategy class has this name", row))

    health_log.info(f"Strategies loaded: {len(runnable)} can run ({sorted(runnable)}), {len(skipped)} skipped")
    return runnable, skipped

def skip_alert(skipped: list) -> str | None:
    """Return the Discord message for the skipped strategies

    Parameters:
        skipped (list): The skipped list from load_strategies

    Returns:
        The message, or None when nothing was skipped
    """
    if not skipped:
        return None
    lines = [f"{len(skipped)} strategy(s) skipped at startup. The others are running. {DISCORD_MENTION}"]
    for skip in skipped:
        line = f"- {skip['name']}: {skip['reason']}"
        if skip["open_positions"]:
            line += (f". It holds {skip['open_positions']} open position(s): "
                     f"its sells won't run until this is fixed.")
        lines.append(line)
    lines.append("Fix the strategy class or its strategies row, then restart.")
    return "\n".join(lines)
