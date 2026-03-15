"""
backtest.py
Responsible for backtesting strategies.
"""

#Third party libraries
import pandas as pd
import numpy as np

def run_backtest(df, ticker, starting_capital=10000):
    """
    Backtests a trading strategy based on generated signals and calculates the portfolio value over time.

    Parameters:
        df: DataFrame containing stock data and trading signals.
        ticker: The stock symbol for labeling the results.
        start_capital: The initial capital for the backtest.
    """

    #Initialize portfolio value and position
    capital = starting_capital
    position = False #False means no position, True means holding the stock
    buy_price = 0
    trades = []
    
    #Iterate through the DataFrame to simulate trades
    for index, row in df.iterrows():
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

    #Calculate risk to reward ratio
    avg_reward = trades_df[trades_df["Profit"] > 0]["Profit"].mean()
    avg_risk = abs(trades_df[trades_df["Profit"] < 0]["Profit"]).mean() if len(trades_df[trades_df["Profit"] < 0]) > 0 else 0
    risk_reward_ratio = f"{(avg_reward / avg_risk):.2f}:1" if avg_risk > 0 else "N/A"

    return {
        "ticker": ticker,
        "starting_capital": starting_capital,
        "final_capital": capital,
        "total_return": capital - starting_capital,
        "percent_return": (capital - starting_capital) / starting_capital * 100,
        "win_rate": len(trades_df[trades_df["Profit"] > 0]) / len(trades_df[trades_df["Type"] == "Sell"]) * 100 if len(trades_df) > 0 else 0,
        "risk/reward": risk_reward_ratio,
        "trades": trades_df
    }

def display_results(results):
    """
    Display the results of a strategy.

    Parameters:
        results: A dictionary containing the results of the backtest.
    """
    print(f"Ticker: {results['ticker']}")
    print(f"Starting Capital: ${results['starting_capital']}")
    print(f"Final Capital: ${results['final_capital']:.2f}")
    print(f"Total Return: ${results['total_return']:.2f}")
    print(f"Return Percentage: {results['percent_return']:.2f}%")
    print(f"Win Rate: {results['win_rate']:.2f}%")
    print(f"Risk/Reward: {results['risk/reward']}")
    print(f"Total Trades: {len(results['trades'])}")
    