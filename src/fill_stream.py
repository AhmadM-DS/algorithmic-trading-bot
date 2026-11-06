"""
fill_stream.py
Start the fill stream process, which records every order event and fill from Alpaca
"""

#Standard Library
import os

#Local Imports
from alpaca_client import create_alpaca_trading_client
from config.settings import load_env_vars
from execution import AlpacaBroker
from fills.stream import FillStream
from storage.connections import get_connection
from storage.events import insert_bot_event

def main():
    trading_mode = load_env_vars()
    api_key = os.environ[f"ALPACA_API_KEY_{trading_mode}"]
    secret_key = os.environ[f"ALPACA_SECRET_KEY_{trading_mode}"]
    paper = trading_mode == "PAPER"
    broker = AlpacaBroker(create_alpaca_trading_client(api_key=api_key, secret_key=secret_key, paper=paper))
    conn = get_connection()
    try:
        insert_bot_event(conn, "fill_stream_started", f"{trading_mode.lower()} account")
        conn.commit()
    finally:
        conn.close()
    FillStream(broker, api_key, secret_key, paper).run()

if __name__ == "__main__":
    main()
