"""
trader.py
Placing an order with Alpaca API.
"""

#Local Import
from alpaca_client import api, tradeapi
from db import update_order_status
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

def place_market_order(ticker, quantity, side):
    """
    Place a buy or sell order using custom arguments.

    Parameters:
        ticker: The stock symbol to buy.
        quantity: The amount of shares to buy.
        side: Define a buy or sell order.
    """
    try:
        order = api.submit_order(
            symbol=ticker,
            qty=quantity,
            side=side,
            type="market",
            time_in_force="day"
        )
        logger.info(f"Order to {side} {quantity} shares of ${ticker} has been placed.")
        send_trades(f"Order to {side} {quantity} shares of ${ticker} has been placed.")
        return {"Order Placed": order}
    except tradeapi.rest.APIError as e:
        reason = str(e)
        logger.error(f"Unable to {side} {quantity} shares of ${ticker}. Reason: {reason}")
        send_trades(f"Unable to {side} {quantity} shares of ${ticker}. Reason: {reason}")
        return {"Order Failed": reason}

# TODO: place_bracket_order(ticker, quantity, entry_price, take_profit_pct, stop_loss_pct)
# Per-trade exit — submit the buy via api.submit_order(..., order_class="bracket",
# take_profit={"limit_price": entry_price * (1 + take_profit_pct)},
# stop_loss={"stop_price": entry_price * (1 - stop_loss_pct)}) so Alpaca closes the
# position automatically instead of waiting for the next run() slot to notice.
# Swap this in for place_market_order's buy call in main.py once ready.
"""
We created a risk management tool that stops the bot from placing trades once 
a strategy reaches it's target or it's maximum loss but we don't have a method to
sell that stock once we've hit target/max loss. 
This is where place_bracket_order() comes in.
"""

def sync_order_statuses(conn):
    open_orders = api.list_orders(status='open')
    for order in open_orders:
        update_order_status(conn, order.id, order.status)
        logger.info(f"Updated {order.id} to {order.status}")
