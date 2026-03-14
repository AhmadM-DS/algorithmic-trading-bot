"""
cleaner.py
Responsible for cleaning the data obtained from Yahoo Finance 
and preparing it for use in trading strategies.
"""
#Third party libraries
import yfinance as yf
import pandas as pd

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

    #Resetting the index and leveling columns
    raw_data.columns = raw_data.columns.get_level_values(0)
    raw_data.reset_index(inplace=True)

    #Save the raw data to a CSV file for later use
    raw_data.to_csv(f"../data/raw/{ticker}_raw.csv", index=False)

    return raw_data

def clean_data(ticker):
    """
    Cleans raw stock data for a given ticker symbol
    Parameters:
        ticker (str): The stock symbol to clean data for.
    """

    #Load raw data from csv
    df = pd.read_csv(f"../data/raw/{ticker}_raw.csv")

    #Drop rows with missing values
    df.dropna(inplace=True)

    #Convert 'Date' column to datetime format
    df["Date"] = pd.to_datetime(df["Date"])

    #Save the cleaned data to a new CSV file
    df.to_csv(f"../data/cleaned/{ticker}_cleaned.csv", index=False)

    return df
