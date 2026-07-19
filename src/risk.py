"""
risk.py
Handles the risk management logic.
"""

from config import DEFAULT_LOSS_LIMIT, DEFAULT_PROFIT_TARGET
from notifications import send_routine
from logger import get_logger
logger = get_logger(__name__)


class DailyRiskState:
    """
    Handles the criteria for what strategies can place trades.
    Re-entry after a same-day close is blocked on purpose, enforced in signals_executed_today.
    """
    profit_target = DEFAULT_PROFIT_TARGET
    loss_limit = DEFAULT_LOSS_LIMIT
    def __init__(self):
        self.signals_executed_today = set()
        self.strategy_cost_basis = {}
        self.strategy_realized_pnl = {}
        self.strategy_entry_prices = {}
        self.halted_strategies = set()

    def reset_daily_state(self):
        self.signals_executed_today.clear()
        self.strategy_cost_basis.clear()
        self.strategy_realized_pnl.clear()
        self.strategy_entry_prices.clear()
        self.halted_strategies.clear()

    def record_buy(self, ticker, strategy_name, price, quantity):
        """
        Called after a buy order is confirmed placed.
        """
        buy_key = (ticker, strategy_name, "buy")
        if buy_key in self.signals_executed_today:
            logger.info(f"Duplicate buy signal skipped: {strategy_name} on {ticker}.")
            return
        self.signals_executed_today.add(buy_key)
        self.strategy_cost_basis[strategy_name] = self.strategy_cost_basis.get(strategy_name, 0) + price * quantity
        self.strategy_entry_prices[(strategy_name, ticker)] = (price, quantity)

    def record_sell(self, ticker, strategy_name, price, quantity):
        """
        Called after a sell order is confirmed placed.
        """
        sell_key = (ticker, strategy_name, "sell")
        if sell_key in self.signals_executed_today:
            logger.info(f"Duplicate sell signal skipped: {strategy_name} on {ticker}")
            return
        self.signals_executed_today.add(sell_key)
        entry = self.strategy_entry_prices.pop((strategy_name, ticker), None)
        if entry:
            entry_price, entry_qty = entry
            if quantity != entry_qty:
                logger.warning(f"Sell quantity ({quantity}) != recorded entry quantity ({entry_qty}) for {strategy_name} on {ticker}.")
            pnl = (price - entry_price) * entry_qty
            self.strategy_realized_pnl[strategy_name] = self.strategy_realized_pnl.get(strategy_name, 0) + pnl

    def already_executed(self, ticker, strategy_name, side):
        """
        True if (ticker, strategy_name, side) has already been acted on
        today — check before placing an order to avoid a duplicate trade.
        """
        return (ticker, strategy_name, side) in self.signals_executed_today

    def get_entry_quantity(self, strategy_name, ticker):
        """
        Return the recorded entry quantity for (strategy_name, ticker), or
        None if there's no recorded entry.
        """
        entry = self.strategy_entry_prices.get((strategy_name, ticker))
        return entry[1] if entry else None

    def is_halted(self, strategy_name):
        """
        Called before evaluating a strategy's signal for a ticker.
        """
        if strategy_name in self.halted_strategies:
            return True
        cost = self.strategy_cost_basis.get(strategy_name, 0)
        if cost == 0:
            return False
        roi = self.strategy_realized_pnl.get(strategy_name, 0) / cost
        if roi >= self.profit_target:
            self.halted_strategies.add(strategy_name)
            logger.info(f"Strategy {strategy_name} halted: profit target reached ({roi:.1%} ROI).")
            send_routine(f"Strategy {strategy_name} halted for today: profit target reached ({roi:.1%} ROI).")
            return True
        if roi <= self.loss_limit:
            self.halted_strategies.add(strategy_name)
            logger.info(f"Strategy {strategy_name} halted: loss limit reached ({roi:.1%} ROI).")
            send_routine(f"Strategy {strategy_name} halted for today: loss limit reached ({roi:.1%} ROI).")
            return True
        return False