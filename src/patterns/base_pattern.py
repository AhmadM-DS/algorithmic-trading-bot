"""
base_pattern.py
Defines our base logic for each price-action pattern used.
"""

class Pattern:
    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        raise NotImplementedError

    def update(self, candles):
        """Streaming mode: For paper & live trading, given the most recent rolling window of candles"""
        raise NotImplementedError
