"""
trader.py
Placing an order with Alpaca API.
"""

#Local Import
from alpaca_client import api, tradeapi
from logger import get_logger
logger = get_logger(__name__)

account = api.get_account()

#Restrictions for placing orders
def is_pdt():
    if float(account.portfolio_value) < 25000 and int(account.daytrade_count) >=3:
        logger.warning("Trade blocked. PDT rule enforced.")
        return True
    return False

def has_buying_power(quantity, price):
    """
    Parameters:
        quantity(int): The amount of shares to be bought.
        price(float): Cost per share.
    """
    order_value = quantity * price
    if float(account.buying_power) < order_value:
        logger.warning("Trade blocked. Not enough funds.")
        return False
    return True

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
        return {"Order Placed": order}
    except tradeapi.rest.APIError:
        logger.error(f"Unable to {side} {quantity} shares of ${ticker}. Order Canceled.")
        return {"Order Failed": f"{side} {quantity} shares of ${ticker}"}
        