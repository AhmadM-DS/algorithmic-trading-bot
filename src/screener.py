"""
screener.py
Create custom screeners per strategy by scrapping TradingView.
"""

#Third Party Library
import requests

#Local imports
from logger import get_logger
logger = get_logger(__name__)

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
    try:
        response = requests.post(URL, json=payload, headers=HEADERS)
        data = response.json()
    except requests.exceptions.RequestException:
        logger.error("HTTP request has failed, possible network failure.")
        return []
    except requests.exceptions.JSONDecodeError:
        logger.error("Reponse returned invalid JSON")
        return []

    tickers = []
    try:
        for item in data["data"]:
            full_ticker = item["s"]
            split_ticker = full_ticker.split(":")
            only_ticker = split_ticker[1]
            tickers.append(only_ticker)
        logger.info(f"{len(tickers)} tickers successfully added to list.")
    except KeyError:
        logger.warning("'data' key missing from response, no tickers added.")
        return []
    
    return tickers