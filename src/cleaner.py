"""
cleaner.py
Responsible for cleaning the data obtained from Yahoo Finance 
and preparing it for use in trading strategies.
"""

#Standard Library
from datetime import date, timedelta
from pathlib import Path

#Third party libraries
import yfinance as yf
import pandas as pd

#Local imports
from config import DEFAULT_LOOKBACK_DAYS
from logger import get_logger

logger = get_logger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
CLEANED_DIR = BASE_DIR / "data" / "cleaned"

def fetch_raw_data(ticker, start_date, end_date):
    """
    Fetches historical stock data from Yahoo Finance for a given ticker symbol and date range.
    Parameters:
        ticker (str): The stock symbol to fetch data for.
        start_date (str): The start date for the data in 'YYYY-MM-DD'
        end_date (str): The end date for the data in 'YYYY-MM-DD'
    """
    #Downloading data using yfinance
    raw_data = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True)

    #If the stock has been delisted or no price available, don't save it
    if raw_data.empty:
        logger.warning(f"Cannot download ticker ${ticker} due to delisting or no price available. File not saved.")
        return None
    else:

        #Resetting the index and leveling columns
        raw_data.columns = raw_data.columns.get_level_values(0)
        raw_data.reset_index(inplace=True)

        #Save the raw data to a CSV file for later use
        raw_data.to_csv(BASE_DIR / "data" / "raw" / f"{ticker}_raw.csv", index=False)
        logger.info(f"Ticker ${ticker} has been saved to raw data folder.")
        return raw_data

def clean_data(ticker):
    """
    Cleans raw stock data for a given ticker symbol
    Parameters:
        ticker (str): The stock symbol to clean data for.
    """

    #Load raw data from csv
    df = pd.read_csv(BASE_DIR / "data" / "raw" / f"{ticker}_raw.csv")

    #Drop rows with missing values
    df.dropna(inplace=True)

    #Convert 'Date' column to datetime format
    df["Date"] = pd.to_datetime(df["Date"])

    #Save the cleaned data to a new CSV file
    df.to_csv(CLEANED_DIR / f"{ticker}_cleaned.csv", index=False)
    logger.info(f"Ticker ${ticker} has been saved to cleaned data folder.")

    return df

def load_ticker_data(ticker, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """
    Return a cleaned DataFrame for ticker, using the cached cleaned CSV if
    one exists. Otherwise fetches and cleans `lookback_days` of history
    ending today. Returns None if no data could be fetched.

    Parameters:
        ticker (str): The stock symbol to load data for.
        lookback_days (int): How many calendar days of history to fetch when
            there's no cached CSV yet — defaults to DEFAULT_LOOKBACK_DAYS but
            callers can pass a different window per strategy's needs.
    """
    cleaned_path = CLEANED_DIR / f"{ticker}_cleaned.csv"
    if cleaned_path.exists():
        return pd.read_csv(cleaned_path)

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    raw_data = fetch_raw_data(ticker, start_date=start_date.isoformat(), end_date=end_date.isoformat())
    if raw_data is None:
        return None
    return clean_data(ticker)
