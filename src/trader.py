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
    except tradeapi.rest.APIError:
        logger.warning("Trade blocked. Position not found.")
        return False

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

def sync_order_statuses(conn):
    open_orders = api.list_orders(status='open')
    for order in open_orders:
        update_order_status(conn, order.id, order.status)
        logger.info(f"Updated {order.id} to {order.status}")
