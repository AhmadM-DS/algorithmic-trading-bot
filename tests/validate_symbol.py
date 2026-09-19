"""
This file validates if a symbol is valid in ALpaca
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alpaca_client import api

def get_price(symbol):
    quote = api.get_latest_quote(symbol)
    return quote

if __name__ == "__main__":
    spy = get_price('NASDAQ')
    print(spy)