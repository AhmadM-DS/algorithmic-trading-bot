"""
technical_indicators.py
Computes the following technical indicators:
    -RSI
    -MACD
    -EMA
    -VWAP
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

class EMA(Indicator):
    def __init__(self, period=9):
        self.period = period
        self.multiplier = 2 / (period + 1)
        self.ema = None

    def calculate(self, df):
        prices = df["close"]
        return prices.ewm(span=self.period, adjust=False).mean()

    def update(self, new_candle):
        close = new_candle["close"]

        #First candle- seed the EMA with the raw close
        if self.ema is None:
            self.ema = close
            return self.ema
        self.ema = (close - self.ema) * self.multiplier + self.ema
        return self.ema

class MACD(Indicator):
    def __init__(self, short_period=12, long_period=26, signal_period=9):
        self.short_period = short_period
        self.long_period = long_period
        self.signal_period = signal_period
        self.short_ema = EMA(short_period)
        self.long_ema = EMA(long_period)
        self.signal_ema = EMA(signal_period)

    def calculate(self, df):
        short_ema = df["close"].ewm(span=self.short_period, adjust=False).mean()
        long_ema = df["close"].ewm(span=self.long_period, adjust=False).mean()
        macd_line = short_ema - long_ema
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        return pd.DataFrame({
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram
        })

    def update(self, new_candle):
        short_value = self.short_ema.update(new_candle)
        long_value = self.long_ema.update(new_candle)
        macd_value = short_value - long_value
        signal_value = self.signal_ema.update({"close": macd_value})
        histogram = macd_value - signal_value
        return {
            "macd_line": macd_value,
            "signal_line": signal_value,
            "histogram": histogram
        }

class VWAP(Indicator):
    def __init__(self):
        self.cumulative_price_volume = 0
        self.cumulative_volume = 0

    def calculate(self, df):
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_price_volume = (typical_price * df["volume"]).cumsum()
        cumulative_volume = df["volume"].cumsum()
        return cumulative_price_volume / cumulative_volume

    def update(self, new_candle):
        typical_price = (new_candle["high"] + new_candle["low"] + new_candle["close"]) / 3
        volume = new_candle["volume"]

        self.cumulative_price_volume += typical_price * volume
        self.cumulative_volume += volume

        if self.cumulative_volume == 0:
            return None
        return self.cumulative_price_volume / self.cumulative_volume