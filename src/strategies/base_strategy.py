"""
base_strategy.py
Defines our base logic for each strategy used.
"""

#Standard Library
import os

#Third party libraries
import pandas as pd
import matplotlib.pyplot as plt

class Strategy:
    #Every strategy will inherit from this parent class
    def __init__(self, name, df, ticker, initial_capital):
        """
        Parameters:
            name (str): The name of the strategy.
            df (DataFrame): Dataframe containing clean stock data.
            ticker (str): The stock symbol for labeling the results.
            initial_capital (int/float): The initial capital for the backtest.
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
        
        #Iterate through the DataFrame to simulate trades
        for _, row in self.df.iterrows():
            if row["signal"] == 1 and not position:
                buy_price = row["Close"]
                position = True
                trades.append({"Date": row["Date"], "Type": "Buy", "Price": buy_price})
            elif row["signal"] == -1 and position:
                sell_price = row["Close"]
                position = False
                profit = sell_price - buy_price
                capital += profit
                trades.append({"Date": row["Date"], "Type": "Sell", "Price": sell_price, "Profit": profit})
        
        #Convert trades to DataFrame for better visualization
        trades_df = pd.DataFrame(trades)

        htl_path = f"../trade_logs/historical_trade_log.csv"
        trades_df["strategy"] = self.name
        trades_df["ticker"] = self.ticker

        if os.path.exists(htl_path):
            old = pd.read_csv(htl_path)
            combined = pd.concat([old, trades_df])
            combined = combined.drop_duplicates(subset=["strategy", "ticker", "Date", "Type"])
            combined.to_csv(htl_path, index=False)
        else:
            trades_df.to_csv(htl_path, index=False)

        if len(trades_df) == 0 or "Profit" not in trades_df.columns:
            return None
        else:
            #Calculate risk to reward ratio
            avg_reward = trades_df[trades_df["Profit"] > 0]["Profit"].mean()
            avg_risk = abs(trades_df[trades_df["Profit"] < 0]["Profit"]).mean() if len(trades_df[trades_df["Profit"] < 0]) > 0 else 0
            risk_reward_ratio = f"{(avg_reward / avg_risk):.2f}:1" if avg_risk > 0 else "N/A"
            
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

            metrics_df = pd.DataFrame([backtest_result_metrics])
            m_path = f"../trade_logs/metrics_log.csv"
            metrics_df["run_date"] = pd.Timestamp.today().date()
            if os.path.exists(m_path):
                old = pd.read_csv(m_path)
                combined = pd.concat([old, metrics_df])
                combined = combined.drop_duplicates(subset=["strategy", "ticker", "run_date"])
                combined.to_csv(m_path, index=False)
            else:
                metrics_df.to_csv(m_path, index=False)

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
        _, ax = plt.subplots(figsize=(14, 7))

        trades_df = pd.read_csv(f"../trade_logs/{self.name}_{self.ticker}_trade_log.csv")
        sells = trades_df[trades_df["Type"] == "Sell"]
        portfolio_value = self.initial_capital + sells["Profit"].cumsum()

        ax.plot(sells["Date"], portfolio_value, label="Portfolio Value", alpha=0.5)

        ax.set_title(f"Portfolio Growth over time for {self.ticker}-{self.name}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Amount")
        ax.legend()
        plt.xticks(rotation=45)
        plt.show()