"""
base_indicator.py
Defines our base logic for each technical indicator used.
"""

class Indicator:
    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        raise NotImplementedError
    
    def update(self, new_candle):
        """Streaming mode: For paper & live trading one candle at a time"""
        raise NotImplementedError