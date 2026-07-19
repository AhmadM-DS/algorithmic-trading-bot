"""
base_strategy.py
Defines our base logic for each strategy used.
"""

#Standard Library
import os

#Third party libraries
import pandas as pd
import matplotlib.pyplot as plt

#Local imports
from logger import get_logger
logger = get_logger(__name__)
from config import DEFAULT_FILTERS
from db import get_connection, insert_trade, insert_metrics

class Strategy:
    #Every strategy will inherit from this parent class
    filters = DEFAULT_FILTERS
    risk_fraction = 0.25
    def __init__(self, name, df, ticker, initial_capital):
        """
        Parameters:
            name (str): The name of the strategy.
            df (DataFrame): Dataframe containing clean stock data.
            ticker (str): The stock symbol for labeling the results.
            initial_capital (float): The initial capital for the backtest.
        """
        self.name = name
        self.df = df
        self.ticker = ticker
        self.initial_capital = initial_capital

    def generate_signals(self):
        #Force child to define custom signals
        raise NotImplementedError
    
    def get_latest_signal(self):
        self.generate_signals()
        return self.df.iloc[-1]["signal"]
    
    def backtest(self):
        """
        Backtests a trading strategy based on generated signals and calculates the portfolio value over time.
        """
        #Generate buy/sell signals before running the backtest logic
        self.generate_signals()

        #Initialize portfolio value and position
        capital = self.initial_capital
        position = False #False means no position, True means holding the stock
        buy_price = 0
        trades = []
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Trades WHERE Strategy = ? AND Ticker = ? AND Trade_Type = ?",
                           (self.name, self.ticker, "Backtest")
                           )
            cursor.execute("DELETE FROM Metrics WHERE Strategy = ? AND Ticker = ?",
                           (self.name, self.ticker)
                           )
            conn.commit()
            logger.info(f"Cleaned {cursor.rowcount} backtest trades for {self.ticker}")
            #Simulate trades
            for _, row in self.df.iterrows():
                if row["signal"] == 1 and not position:
                    buy_price = row["Close"]
                    position = True
                    insert_trade(conn, self.name, self.ticker, side="Buy", quantity=1, price=buy_price, trade_type="Backtest", order_id=None, date=row["Date"])
                    trades.append({"Date": row["Date"], "Type": "Buy", "Price": buy_price})
                elif row["signal"] == -1 and position:
                    sell_price = row["Close"]
                    position = False
                    profit = sell_price - buy_price
                    capital += profit
                    insert_trade(conn, self.name, self.ticker, side="Sell", quantity=1, price=sell_price, trade_type="Backtest", profit=profit, order_id=None, date=row["Date"])
                    trades.append({"Date": row["Date"], "Type": "Sell", "Price": sell_price, "Profit": profit})
            #Convert trades to DataFrame for better visualization
            trades_df = pd.DataFrame(trades)

            if len(trades_df) == 0 or "Profit" not in trades_df.columns:
                logger.warning(f"Trade log is empty, unable to calculate {self.name} metrics for ${self.ticker}.")
                return None
            else:
                #Calculate risk to reward ratio
                avg_reward = trades_df[trades_df["Profit"] > 0]["Profit"].mean()
                avg_risk = abs(trades_df[trades_df["Profit"] < 0]["Profit"]).mean() if len(trades_df[trades_df["Profit"] < 0]) > 0 else 0
                if avg_risk == 0:
                    risk_reward_ratio = None
                else:
                    risk_reward_ratio = round(avg_reward / avg_risk, 2)
                percent_return = (capital - self.initial_capital) / self.initial_capital * 100
                win_rate = len(trades_df[trades_df["Profit"] > 0]) / len(trades_df[trades_df["Type"] == "Sell"]) * 100 if len(trades_df) > 0 else 0
                insert_metrics(conn, self.name, self.ticker, self.initial_capital, capital, percent_return, win_rate, risk_reward_ratio)

        backtest_result_metrics = {
                "strategy": self.name,
                "ticker": self.ticker,
                "starting_capital": self.initial_capital,
                "final_capital": capital,
                "total_return": capital - self.initial_capital,
                "percent_return": (capital - self.initial_capital) / self.initial_capital * 100,
                "win_rate": len(trades_df[trades_df["Profit"] > 0]) / len(trades_df[trades_df["Type"] == "Sell"]) * 100 if len(trades_df) > 0 else 0,
                "risk/reward": risk_reward_ratio
            }
        
        return backtest_result_metrics
    def plot_signals(self, columns):
        """
        Plots the stock price along with buy and sell signals.
        
        Parameters:
            ticker (str): The stock symbol for labeling the plot.
            columns (tuple): A Tuple pair of column and label.
        """
        _, ax = plt.subplots(figsize=(14, 7))
        
        ax.plot(self.df["Date"], self.df["Close"], label="Close Price", alpha=0.5)
        for column, label in columns:
            #Plot closing price and moving averages
            ax.plot(self.df["Date"], self.df[column], label=label, alpha=0.8)

        #Plot buy signals
        ax.scatter(self.df.loc[self.df["signal"] == 1, "Date"],
                self.df.loc[self.df["signal"] == 1, "Close"], 
                marker="^", color="green", label="Buy", zorder=5)

        #Plot sell signals
        ax.scatter(self.df.loc[self.df["signal"] == -1, "Date"],
                self.df.loc[self.df["signal"] == -1, "Close"], 
                marker="v", color="red", label="Sell", zorder=5)

        ax.set_title(f"{self.ticker} {self.name} Strategy")
        ax.set_xlabel("Date")
        ax.set_ylabel("Price")
        ax.legend()
        ax.xaxis.set_major_locator(plt.MaxNLocator(10))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()

    def plot_portfolio_growth(self):
        """
        Plots the growth of the portfolio over time based on the backtest results.
        """
        with get_connection() as conn:
            _, ax = plt.subplots(figsize=(14, 7))

            trades_df = pd.read_sql("SELECT Strategy, Ticker, Side, Profit, Trade_Type, Date FROM Trades "
                                    "WHERE Strategy = ? AND Ticker = ? AND Trade_Type = ?",
                                    conn,
                                    params=(self.name, self.ticker, "Backtest"))
            sells = trades_df[trades_df["Side"] == "Sell"]
            portfolio_value = self.initial_capital + sells["Profit"].cumsum()

            ax.plot(sells["Date"], portfolio_value, label="Portfolio Value", alpha=0.5)

            ax.set_title(f"Portfolio Growth over time for {self.ticker}-{self.name}")
            ax.set_xlabel("Date")
            ax.set_ylabel("Amount")
            ax.legend()
            plt.xticks(rotation=45)
            plt.show()