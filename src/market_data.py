"""
market_data.py
Handles how we get any and all market data
"""

#Third Party Imports
from alpaca.data.requests import StockLatestTradeRequest

def get_latest_price(data_client, ticker):
    """Get the latest price for the underlying stock
    
    Parameters:
        data_client (StockHistoricalDataClient): Alpaca client that retrieves historical stock data
        ticker (str): Symbol retrieved by the screener
    """
    trade_request = StockLatestTradeRequest(symbol_or_symbols=ticker)
    trade_response = data_client.get_stock_latest_trade(trade_request)
    return trade_response[ticker].price