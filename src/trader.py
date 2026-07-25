"""
trader.py
Placing an order with Alpaca API.
"""

#Local Import
from alpaca_client import api, tradeapi
from config import PER_TRADE_PROFIT_TARGET_PCT, PER_TRADE_STOP_LOSS_PCT
from db import update_order_status, insert_order, insert_trade
from notifications import send_trades
from logger import get_logger
logger = get_logger(__name__)

#Restrictions for placing orders
def has_position(ticker):
    """
    Parameters:
        ticker (str): The stock symbol.
    """
    try:
        api.get_position(ticker)
        logger.info("Trade authorized. Position found.")
        return True
    except tradeapi.rest.APIError as e:
        if e.status_code == 404:
            logger.warning("Trade blocked. Position not found.")
            return False
        logger.error(f"Unable to check position for {ticker}, treating as unknown. Reason: {e}")
        raise

def size_position(account, current_price, risk_fraction):
    """
    Compute how many shares to trade for a fixed-fraction position size.

    Parameters:
        account: Alpaca account object (needs .buying_power).
        current_price (float): Latest trade price for the ticker.
        risk_fraction (float): Fraction of buying power to risk on this trade
    """
    return int(float(account.buying_power) * risk_fraction / current_price)

def _is_inactive_asset_error(reason):
    """Detects Alpaca rejections caused by the asset being inactive/not tradable."""
    reason_lower = reason.lower()
    return "not active" in reason_lower or "not tradable" in reason_lower

def place_market_order(conn, ticker, quantity, side, price, entry_price=None):
    """
    Place a buy or sell order using custom arguments.

    Buys are submitted as bracket orders so Alpaca automatically closes the
    position at a +/-5% profit target / stop loss instead of waiting for the
    next run() slot to notice.

    Parameters:
        conn: Open database connection, used to log the order.
        ticker: The stock symbol to buy.
        quantity: The amount of shares to buy.
        side: Define a buy or sell order.
        price: Latest trade price at order time, logged alongside the order.
        entry_price: Original buy price, used to compute realized P/L on a sell.
    """
    try:
        if side == "buy":
            order = api.submit_order(
                symbol=ticker,
                qty=quantity,
                side=side,
                type="market",
                time_in_force="day",
                order_class="bracket",
                take_profit={"limit_price": round(price * (1 + PER_TRADE_PROFIT_TARGET_PCT), 2)},
                stop_loss={"stop_price": round(price * (1 - PER_TRADE_STOP_LOSS_PCT), 2)}
            )
        else:
            order = api.submit_order(
                symbol=ticker,
                qty=quantity,
                side=side,
                type="market",
                time_in_force="day"
            )

        profit = None
        if side == "sell" and entry_price is not None:
            profit = (price - entry_price) * quantity
            pct_change = (price - entry_price) / entry_price * 100
            message = (f"Order to sell {quantity} shares of ${ticker} has been placed. "
                       f"P/L: ${profit:.2f} ({pct_change:+.2f}%)")
        else:
            message = f"Order to {side} {quantity} shares of ${ticker} has been placed."
        logger.info(message)
        send_trades(message)
        order_id = insert_order(conn, order.id, ticker, side, quantity, price, order.status, profit=profit)
        return {"Order Placed": order, "Order_ID": order_id}
    except tradeapi.rest.APIError as e:
        reason = str(e)
        logger.error(f"Unable to {side} {quantity} shares of ${ticker}. Reason: {reason}")
        send_trades(f"Unable to {side} {quantity} shares of ${ticker}. Reason: {reason}")
        return {"Order Failed": reason, "Inactive": _is_inactive_asset_error(reason)}

def reconcile_bracket_exits(conn, risk_state):
    """
    Detects positions that Alpaca closed on its own via a bracket order's
    take-profit/stop-loss leg and records the realized P/L so daily risk tracking and
    the Trades table stay accurate.
    """
    for (strategy_name, ticker), (entry_price, _entry_qty) in list(risk_state.strategy_entry_prices.items()):
        if has_position(ticker):
            continue
        closed_sells = api.list_orders(status="closed", symbols=[ticker], side="sell", direction="desc", limit=5)
        fill = next((o for o in closed_sells if o.status == "filled"), None)
        if fill is None:
            logger.warning(f"Position for {ticker} ({strategy_name}) closed but no filled sell order found; cannot reconcile yet.")
            continue
        fill_price = float(fill.filled_avg_price)
        fill_qty = int(float(fill.filled_qty))
        profit = (fill_price - entry_price) * fill_qty
        pct_change = (fill_price - entry_price) / entry_price * 100
        risk_state.record_sell(ticker, strategy_name, fill_price, fill_qty)
        insert_trade(conn, strategy_name, ticker, side="sell", quantity=fill_qty,
                     price=fill_price, trade_type="Live", profit=profit, order_id=None)
        message = (f"Bracket exit filled: sold {fill_qty} shares of {ticker} ({strategy_name}) "
                   f"at ${fill_price:.2f}. P/L: ${profit:.2f} ({pct_change:+.2f}%)")
        logger.info(message)
        send_trades(message)

def sync_order_statuses(conn):
    open_orders = api.list_orders(status='open')
    for order in open_orders:
        update_order_status(conn, order.id, order.status)
        logger.info(f"Updated {order.id} to {order.status}")
