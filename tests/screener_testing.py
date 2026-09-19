"""
screener_testing.py
Manual test harness for screener.py. Runs the screener once at a fixed
time today (default 19:00) so results can be checked the same evening
instead of waiting for the next 09:30 market-hours run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import DEFAULT_FILTERS
from screener import get_tickers

RUN_AT = "15:15"


def run_screener_test():
    print(f"Running screener with filters: {DEFAULT_FILTERS}")
    tickers = get_tickers(DEFAULT_FILTERS)
    print(f"Found {len(tickers)} tickers: {tickers}")


if __name__ == "__main__":
    run_screener_test()
