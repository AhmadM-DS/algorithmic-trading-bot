"""
db.py
Connect to Azure SQL.
"""

#Third party libraries
import pyodbc
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

#Local imports
from logger import get_logger
logger = get_logger(__name__)


def get_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")
    username = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )
    return conn

def insert_order(conn, alpaca_order_id, ticker, side, quantity, price, status, profit=None, date=None):
    if date is None:
        date = datetime.now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Orders (Alpaca_Order_ID, Ticker, Side, Quantity, Price, Status, Profit, Date) "
        "OUTPUT INSERTED.Order_ID "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (alpaca_order_id, ticker, side, quantity, price, status, profit, date)
    )
    new_id = cursor.fetchone()[0]
    conn.commit()
    logger.info(f"Inserted order {new_id} for {ticker} into TradingBot.Orders")
    return new_id


def insert_trade(conn, strategy, ticker, side, quantity, price, trade_type, profit = None, order_id=None, date=None):
    if date is None:
        date = datetime.now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Trades (Strategy, Ticker, Side, Quantity, Price, Date, Order_ID, Trade_Type, Profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (strategy, ticker, side, quantity, price, date, order_id, trade_type, profit)
    )
    logger.info(f"Inserted trade for {ticker} into TradingBot.Trades")
    conn.commit()

def insert_metrics(conn, strategy, ticker, starting_capital, final_capital, percent_return, win_rate, risk_reward=None, date=None):
    if date is None:
        date = datetime.now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Metrics (Strategy, Ticker, Starting_Capital, Final_Capital, Percent_Return, Win_Rate, Risk_Reward, Date) " 
        "VALUES (?,?, ?, ?, ?, ?, ?, ?)",
        (strategy, ticker, starting_capital, final_capital, percent_return, win_rate, risk_reward, date)
    )
    logger.info(f"Metrics inserted into TradingBot.Metrics for {ticker}")
    conn.commit()

def get_open_orders(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT Alpaca_Order_ID, Status FROM Orders WHERE Status IN ('new', 'pending', 'partially_filled', 'accepted')"
    )
    open_order_id = cursor.fetchall()
    return open_order_id

def update_order_status(conn, alpaca_order_id, status):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE Orders SET Status = ? WHERE Alpaca_Order_ID = ?",
        (status, alpaca_order_id)
    )
    conn.commit()
    logger.info(f"Updated {cursor.rowcount} rows to {status} status")