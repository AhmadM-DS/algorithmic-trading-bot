"""
screener.py
Screen for momentum tickers using the Financial Modeling Prep (FMP) API
for gainers/float data and yfinance for relative-volume history.
"""

#Standard Library
import os
import time
from pathlib import Path

#Third Party Library
import requests
import yfinance as yf
from dotenv import load_dotenv

#Local imports
from logger import get_logger
logger = get_logger(__name__)

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
API_KEY = os.getenv("FMP_API_KEY")

BASE_URL = "https://financialmodelingprep.com/stable"
RELATIVE_VOLUME_LOOKBACK_DAYS = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def _get(endpoint, params=None):
    """
    Issues a GET request against an FMP `stable` endpoint and returns the
    parsed JSON body, or None if the request/response was invalid.

    Transient failures (timeouts, connection errors, 429/5xx responses) are
    retried with backoff; 4xx errors other than 429 fail immediately since
    retrying won't fix a bad request or permissions issue.
    """
    params = dict(params or {})
    params["apikey"] = API_KEY
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 429 or status >= 500:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_SECONDS * attempt
                    logger.warning(
                        f"'{endpoint}' returned {status}, retrying in {wait}s "
                        f"(attempt {attempt}/{MAX_RETRIES})."
                    )
                    time.sleep(wait)
                    continue
            logger.error(
                f"HTTP request to '{endpoint}' failed with status "
                f"{status}: {e.response.text[:300]}"
            )
            return None
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    f"HTTP request to '{endpoint}' failed ({e}), retrying in {wait}s "
                    f"(attempt {attempt}/{MAX_RETRIES})."
                )
                time.sleep(wait)
                continue
            logger.error(f"HTTP request to '{endpoint}' has failed, possible network failure: {e}")
            return None
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Response from '{endpoint}' returned invalid JSON.")
            return None
    return None


def _get_gainers():
    """
    Returns today's biggest percentage gainers market-wide, as a list of
    {"symbol", "price", "changesPercentage"} dicts.
    """
    data = _get("biggest-gainers")
    if not isinstance(data, list):
        logger.warning("Unexpected response shape from 'biggest-gainers', no tickers added.")
        return []
    return data


def _get_relative_volume(symbol):
    """
    Returns today's volume divided by the average volume over the prior
    RELATIVE_VOLUME_LOOKBACK_DAYS trading days for `symbol`, or None if
    there isn't enough history to compute it.
    """
    history = yf.download(symbol, period=f"{RELATIVE_VOLUME_LOOKBACK_DAYS + 5}d", progress=False)
    if history.empty or len(history) < RELATIVE_VOLUME_LOOKBACK_DAYS + 1:
        return None

    volumes = history["Volume"].squeeze(axis="columns").tail(RELATIVE_VOLUME_LOOKBACK_DAYS + 1)
    today_volume = volumes.iloc[-1]
    avg_prior_volume = volumes.iloc[:-1].mean()

    if avg_prior_volume == 0:
        return None
    return float(today_volume / avg_prior_volume)


def _get_float_shares(symbol):
    """
    Returns the current floating share count for `symbol`, or None if
    unavailable.
    """
    data = _get("shares-float", {"symbol": symbol})
    if not isinstance(data, list) or not data:
        return None
    return data[0].get("floatShares")


def get_tickers(filters):
    """
    Screens today's market gainers down to tickers matching `filters`.

    Parameters:
        filters (dict): price_min, price_max, change_min,
            relative_volume_min, float_min, float_max (see config.DEFAULT_FILTERS).
    """
    gainers = _get_gainers()

    price_filtered = [
        ticker for ticker in gainers
        if filters["price_min"] <= ticker.get("price", 0) <= filters["price_max"]
        and ticker.get("changesPercentage", 0) > filters["change_min"]
    ]

    tickers = []
    for ticker in price_filtered:
        symbol = ticker["symbol"]

        relative_volume = _get_relative_volume(symbol)
        if relative_volume is None or relative_volume <= filters["relative_volume_min"]:
            continue

        float_shares = _get_float_shares(symbol)
        if float_shares is None or not (filters["float_min"] <= float_shares <= filters["float_max"]):
            continue

        tickers.append(symbol)

    logger.info(f"{len(tickers)} tickers successfully added to list.")
    return tickers
