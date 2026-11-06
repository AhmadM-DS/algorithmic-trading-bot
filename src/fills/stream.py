"""
stream.py
The fill stream process: listens to Alpaca's trade updates in one thread and catches up every minute in another
"""

#Standard Library
import json
import threading
import time
from datetime import datetime, timezone

#Third Party Libraries
import pyodbc
from alpaca.trading.stream import TradingStream

#Local Imports
from config.constants import CATCH_UP_SECONDS
from execution.broker import BrokerUnavailable
from fills.catch_up import catch_up
from fills.events import from_stream
from fills.handler import process_update
from logger import trades_log
from notifications import send_critical, send_trades
from storage.connections import get_connection
from storage.events import insert_bot_event
from storage.fills import save_broker_event

def _utc_now() -> datetime:
    """Return the current UTC time without a time zone, as the database stores it"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class FillStream:
    """Records every trade update from Alpaca, and every minute catches up on what it missed

    The stream runs in a background thread with its own database connection; the main thread runs the
    catch-up loop and stops the process if the stream thread dies, so systemd restarts it.
    """

    def __init__(self, broker, api_key: str = None, secret_key: str = None, paper: bool = True,
                 connect=get_connection, alert_channels: dict = None):
        """Set up the stream and the catch-up

        Parameters:
            broker (AlpacaBroker): For the catch-up's lookups
            api_key (str): Alpaca key for the stream; None skips building the stream (tests)
            secret_key (str): Alpaca secret for the stream
            paper (bool): True for the paper account's stream
            connect (callable): Opens a database connection
            alert_channels (dict): {"critical": send, "trades": send}; Discord if None
        """
        self.broker = broker
        self.connect = connect
        self.alert_channels = alert_channels or {"critical": send_critical, "trades": send_trades}
        self.alerted = set()
        self.stream_conn = None
        self.stream = None
        if api_key is not None:
            self.stream = TradingStream(api_key, secret_key, paper=paper, raw_data=True)
            self.stream.subscribe_trade_updates(self._on_message)

    def send_alerts(self, alerts: list):
        """Send each alert once per run, so a fill retried every minute doesn't repeat its alert

        Parameters:
            alerts (list): (channel, message) pairs, channel "critical" or "trades"
        """
        for channel, message in alerts:
            if message not in self.alerted:
                self.alerted.add(message)
                self.alert_channels[channel](message)

    def _stream_connection(self):
        """Return the stream thread's connection, opening it if needed"""
        if self.stream_conn is None:
            self.stream_conn = self.connect()
        return self.stream_conn

    def _drop_stream_connection(self):
        """Forget a broken connection so the next message opens a new one"""
        try:
            self.stream_conn.close()
        except (pyodbc.Error, AttributeError):
            pass
        self.stream_conn = None

    def handle_message(self, data: dict):
        """Save and handle one stream message; never raises, so the stream keeps listening

        Parameters:
            data (dict): The message's "data" part
        """
        try:
            update = from_stream(data)
        except (KeyError, TypeError, ValueError) as error:
            trades_log.error(f"Couldn't read a trade update ({error}); saving it raw: {data}")
            self._save_unreadable(data)
            return
        try:
            result = process_update(self._stream_connection(), update, _utc_now())
        except pyodbc.Error as error:
            self._drop_stream_connection()
            trades_log.error(f"Couldn't save {update.event_type} for {update.alpaca_order_id}: {error}")
            self.send_alerts([("critical", f"The fill stream couldn't save a {update.event_type} for "
                                           f"{update.ticker} ({update.alpaca_order_id}): {error}. "
                                           "The catch-up will look for it every minute.")])
            return
        self.send_alerts(result.alerts)

    def _save_unreadable(self, data: dict):
        """Keep a message the parser couldn't read, raw, so nothing Alpaca sent is lost"""
        try:
            conn = self._stream_connection()
            save_broker_event(conn, event_type=str(data.get("event", "unreadable"))[:30], alpaca_order_id=None,
                              client_order_id=None, execution_id=data.get("execution_id"), ticker=None,
                              event_at=None, raw_json=json.dumps(data, default=str))
            conn.commit()
        except pyodbc.Error as error:
            self._drop_stream_connection()
            trades_log.error(f"Couldn't save an unreadable trade update: {error}")
        self.send_alerts([("critical", f"The fill stream got a message it couldn't read (event "
                                       f"{data.get('event')!r}); saved raw in broker_events.")])

    async def _on_message(self, message: dict):
        self.handle_message(message["data"])

    def catch_up_once(self):
        """Run one catch-up with a fresh connection; log and alert instead of raising"""
        try:
            conn = self.connect()
        except pyodbc.Error as error:
            self.send_alerts([("critical", f"The fill stream can't reach the database for its catch-up: {error}")])
            return
        try:
            result = catch_up(conn, self.broker, _utc_now())
            if result.found_anything:
                insert_bot_event(conn, "fill_catch_up", f"{result.fills} missed fills, {result.status_changes} "
                                                        f"status changes, {result.retried} fills retried")
                conn.commit()
            self.send_alerts(result.alerts)
        except BrokerUnavailable as error:
            trades_log.warning(f"Catch-up skipped, Alpaca didn't answer: {error}")
        except Exception as error:
            trades_log.error(f"Catch-up failed: {type(error).__name__}: {error}")
            self.send_alerts([("critical", f"The fill stream's catch-up failed ({type(error).__name__}: {error}). "
                                           "It tries again every minute.")])
        finally:
            conn.close()

    def run(self, catch_up_seconds: int = CATCH_UP_SECONDS):
        """Start listening, then catch up every catch_up_seconds until the stream thread stops

        The stream starts first and the catch-up right after, so nothing slips between them.

        Parameters:
            catch_up_seconds (int): Seconds between catch-ups

        Raises:
            SystemExit(1) if the stream thread stops, so systemd restarts the process
        """
        listener = threading.Thread(target=self.stream.run, name="trade-updates", daemon=True)
        listener.start()
        trades_log.info("Fill stream started")
        while listener.is_alive():
            self.catch_up_once()
            time.sleep(catch_up_seconds)
        trades_log.critical("The trade-updates stream stopped; exiting so the process restarts")
        self.send_alerts([("critical", "The fill stream's listener stopped; the process is exiting to restart.")])
        raise SystemExit(1)
