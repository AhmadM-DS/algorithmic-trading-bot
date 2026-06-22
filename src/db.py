"""
db.py
Connect to SQL Server.
"""

#Third party libraries
import pyodbc
from datetime import datetime


def get_connection():
    conn = pyodbc.connect(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=.\\SQLEXPRESS;"
    "DATABASE=TradingBot;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
    )
    return conn

def insert_order(conn, alpaca_order_id, ticker, side, quantity, price, status, profit=None, date=None):
    if date is None:
        date = datetime.now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Orders (Alpaca_Order_ID, Ticker, Side, Quantity, Price, Status, Profit, Date) "
        "OUTPUT INSERTED.ORDER_ID "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (alpaca_order_id, ticker, side, quantity, price, status, profit, date)
    )
    new_id = cursor.fetchone()[0]
    conn.commit()
    return new_id


def insert_trade(conn, strategy, ticker, side, quantity, price, trade_type, order_id=None, date=None):
    if date is None:
        date = datetime.now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Trades (Strategy, Ticker, Side, Quantity, Price, Date, Order_ID, Trade_Type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (strategy, ticker, side, quantity, price, date, order_id, trade_type)
    )
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
    conn.commit()

if __name__ == "__main__":
    with get_connection() as conn:
        """new_id = insert_order(conn, "test123456789", "TLSA", "Sell", 100, 35, "Open")
        insert_trade(conn, "MACD", "TLSA", "Sell", 100, 36, order_id=new_id)
        print("Order inserted")"""
        pass