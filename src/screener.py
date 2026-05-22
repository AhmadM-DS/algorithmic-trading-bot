"""
screener.py
Create custom screeners per strategy by scrapping TradingView.
"""

#Third Party Library
import requests

URL = "https://scanner.tradingview.com/america/scan?label-product=screener-stock"

HEADERS = {
    "user-agent": "Mozilla/5.0 ..."
}

def get_tickers(filters):
    payload = {
        "columns": ["name"],
        "filter": filters,
        "markets": ["america"],
        "options": {"lang": "en"},
        "range": [0, 100],
        "sort": {"sortBy": "change", "sortOrder": "desc"}
    }

    response = requests.post(URL, json=payload, headers=HEADERS)
    data = response.json()

    tickers = []
    for item in data["data"]:
        full_ticker = item["s"]
        split_ticker = full_ticker.split(":")
        only_ticker = split_ticker[1]
        tickers.append(only_ticker)
    
    return tickers