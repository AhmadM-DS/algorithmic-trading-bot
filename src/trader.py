"""
trader.py
Placing an order with Alpaca API.
"""

#Local Import
from alpaca_client import api

account = api.get_account()

#Restrictions for placing orders
def is_pdt():
    if float(account.portfolio_value) < 25000 and int(account.daytrade_count) >=3:
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
        return False
    return True

def has_position(ticker):
    """
    Parameters:
        ticker (str): The stock symbol.
    """
    try:
        api.get_position(ticker)
        return True
    except:
        return False

def place_market_order(ticker, quantity, side):
    """
    Place a buy or sell order using custom arguments.

    Parameters:
        ticker: The stock symbol to buy.
        quantity: The amount of shares to buy.
        side: Define a buy or sell order.
    """
    order = api.submit_order(
        symbol=ticker,
        qty=quantity,
        side=side,
        type="market",
        time_in_force="day"
    )

    return {"Order Placed": order}