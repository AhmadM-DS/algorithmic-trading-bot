"""
shares.py
Compare the shares Alpaca holds of each ticker with the shares the database says the bot holds
"""

#Standard Library
from dataclasses import dataclass

#Local Imports
from storage.fills import fits_ticker

@dataclass(frozen=True)
class ShareCounts:
    """One ticker's share count at Alpaca and in the database (open positions of every strategy, summed)"""
    alpaca: int
    database: int

    @property
    def short(self) -> bool:
        """Return True if Alpaca shows a short position, which the bot never opens"""
        return self.alpaca < 0

def database_shares(positions) -> dict:
    """Return the shares held per ticker, summed over every open position whatever its strategy

    Parameters:
        positions (iterable): Objects with ticker and shares_held, e.g. RiskContext.open_positions

    Returns:
        {ticker: shares}; tickers with no open position are left out
    """
    totals = {}
    for position in positions:
        totals[position.ticker] = totals.get(position.ticker, 0) + position.shares_held
    return totals

def compare_shares(alpaca: dict, database: dict) -> dict:
    """Return every ticker whose share counts differ between Alpaca and the database

    A ticker held on only one side counts as 0 on the other. A negative count at Alpaca (a short) always
    counts, even if the database somehow shows the same number. A position whose symbol doesn't fit the ticker
    columns (an option) is left out: the database can't hold it (BUG-26), so it would mismatch every check.

    Parameters:
        alpaca (dict): {ticker: shares} from AlpacaBroker.get_positions
        database (dict): {ticker: shares} from database_shares

    Returns:
        {ticker: ShareCounts}, empty if everything matches
    """
    mismatches = {}
    alpaca = {ticker: shares for ticker, shares in alpaca.items() if fits_ticker(ticker)}
    for ticker in sorted(set(alpaca) | set(database)):
        counts = ShareCounts(alpaca=alpaca.get(ticker, 0), database=database.get(ticker, 0))
        if counts.alpaca != counts.database or counts.short:
            mismatches[ticker] = counts
    return mismatches
