"""
technical_indicators.py
Computes the following technical indicators:
    -RSI
    -MACD
    ADD TO LIST AS WE COMPUTE MORE
"""

#Standard Library
#Third Party Library
import pandas as pd
#Local Imports
from indicators.base_indicator import Indicator

class RSI(Indicator):
    def __init__(self, period=14):
        self.period = period
        self.prev_close = None
        self.avg_gain = None
        self.avg_loss = None
        self.gains = []
        self.losses = []

    def calculate(self, df):
        prices = df["close"]
        deltas = prices.diff().dropna()
        gains = deltas.where(deltas > 0, 0)
        losses = (-deltas).where(deltas < 0, 0)

        avg_gain = gains.rolling(self.period).mean()
        avg_loss = losses.rolling(self.period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def update(self, new_candle):
        close = new_candle["close"]

        #First candle- no previous close to diff against
        if self.prev_close is None:
            self.prev_close = close
            return None
        delta = close - self.prev_close
        self.prev_close = close
        gain = max(delta, 0)
        loss = max(-delta, 0)

        if self.avg_gain is None:
            self.gains.append(gain)
            self.losses.append(loss)
            if len(self.gains) < self.period:
                return None
            self.avg_gain = sum(self.gains) / len(self.gains)
            self.avg_loss = sum(self.losses) / len(self.losses)
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period
        if self.avg_loss == 0:
            return 100.00
        rs = self.avg_gain / self.avg_loss
        return 100 - (100 / (1 + rs))