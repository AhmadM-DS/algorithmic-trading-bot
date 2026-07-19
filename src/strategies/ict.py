"""
ict.py
Implements the ICT (Inner Circle Trader) Liquidity Sweep Strategy.
"""

#Local Imports
from strategies.base_strategy import Strategy
from patterns.candlestick_patterns import LiquiditySweep, MarketStructureShift, FairValueGap
from logger import get_logger
logger = get_logger(__name__)

"""
Strategy Workflow
The ICT Liquidity Sweep Strategy looks for a single candle that sweeps out
sell-side liquidity below a recent swing low and gets immediately
rejected, then waits for a Change of Character (CHoCH) - a close back
above the recent swing high - confirming the shift in market structure.
The move into that CHoCH must also have left behind a bullish Fair Value
Gap, ICT's signature sign of displacement. Once confirmed, the entry is
placed at the order block: the last bearish candle before the
displacement move. The stop sits below the order block's low, and the
target is a fixed reward/risk multiple of that risk.
"""

class ICT(Strategy):
    swing_lookback = 10
    choch_lookahead = 10
    reward_risk_ratio = 2

    def generate_signals(self):
        """
        Buys on a sell-side liquidity sweep followed by a bullish CHoCH and
        confirming Fair Value Gap, entering at the order block low with a
        stop below it, then exits at a reward/risk target or that stop.
        """
        sweeps = LiquiditySweep(swing_lookback=self.swing_lookback).calculate(self.df)
        shifts = MarketStructureShift(swing_lookback=self.swing_lookback).calculate(self.df)
        fvgs = FairValueGap().calculate(self.df)

        self.df["signal"] = 0
        signal_col = self.df.columns.get_loc("signal")

        in_position = False
        stop_price = None
        target_price = None
        awaiting_choch_since = None

        for i in range(len(self.df)):
            row = self.df.iloc[i]

            if in_position:
                hit_stop = row["Close"] <= stop_price
                hit_target = row["Close"] >= target_price
                if hit_stop or hit_target:
                    self.df.iloc[i, signal_col] = -1
                    in_position = False
                    stop_price = None
                    target_price = None
                continue

            #Track the most recent sell-side liquidity sweep - it stays
            #"live" for choch_lookahead candles while we wait for CHoCH
            sweep = sweeps.iloc[i]
            if sweep is not None and sweep["direction"] == "bullish":
                awaiting_choch_since = i

            if awaiting_choch_since is None:
                continue

            if i - awaiting_choch_since > self.choch_lookahead:
                awaiting_choch_since = None
                continue

            shift = shifts.iloc[i]
            if shift is None or shift["direction"] != "bullish":
                continue

            #CHoCH confirmed - the order block is the last bearish candle
            #before this displacement candle, searching back to the sweep
            order_block_idx = None
            for j in range(i - 1, awaiting_choch_since - 1, -1):
                if self.df["Close"].iloc[j] < self.df["Open"].iloc[j]:
                    order_block_idx = j
                    break

            if order_block_idx is None:
                awaiting_choch_since = None
                continue

            #Displacement should have also left behind a bullish Fair
            #Value Gap somewhere between the order block and the CHoCH
            has_bullish_fvg = any(
                fvgs.iloc[k] is not None and fvgs.iloc[k]["direction"] == "bullish"
                for k in range(order_block_idx, i + 1)
            )
            if not has_bullish_fvg:
                awaiting_choch_since = None
                continue

            order_block_low = self.df["Low"].iloc[order_block_idx]
            entry_price = row["Close"]
            risk = entry_price - order_block_low
            if risk <= 0:
                awaiting_choch_since = None
                continue

            stop_price = order_block_low
            target_price = entry_price + risk * self.reward_risk_ratio
            self.df.iloc[i, signal_col] = 1
            in_position = True
            awaiting_choch_since = None
