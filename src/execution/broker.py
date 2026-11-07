"""
broker.py
The only module that places, finds and cancels orders through alpaca-py
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

#Third Party Libraries
import requests
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import AssetClass, AssetStatus, OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (GetAssetsRequest, GetOrderByIdRequest, MarketOrderRequest, StopLossRequest,
                                     TakeProfitRequest)

#Local Imports
from config.constants import ACTIVITY_PAGE_SIZE

DUPLICATE_MESSAGE = "client_order_id must be unique"

class BrokerError(Exception):
    """Base for every error broker.py raises"""

class OrderRejected(BrokerError):
    """Alpaca refused the order; sending it again won't help"""

class DuplicateOrder(BrokerError):
    """Alpaca already has an order with this client_order_id, so an earlier send got through"""

class BrokerUnavailable(BrokerError):
    """No usable answer (timeout, lost connection, server error); the order may or may not exist"""

@dataclass(frozen=True)
class BrokerOrder:
    """Alpaca's version of one order"""
    alpaca_order_id: str
    client_order_id: str
    side: str
    order_type: str
    time_in_force: str
    status: str
    quantity: int
    filled_quantity: int
    filled_price: Decimal | None
    stop_price: Decimal | None
    limit_price: Decimal | None
    legs: tuple = ()

@dataclass(frozen=True)
class BrokerAccount:
    """The account numbers risk reads: worth now, worth at yesterday's close, and what Alpaca lets it spend"""
    equity: Decimal
    last_equity: Decimal
    buying_power: Decimal

def _to_decimal(value) -> Decimal | None:
    """Turn one of Alpaca's number strings into a Decimal, keeping None"""
    return None if value is None else Decimal(str(value))

def _to_broker_order(order) -> BrokerOrder:
    """Copy an alpaca-py Order (and its legs) into a BrokerOrder"""
    return BrokerOrder(
        alpaca_order_id=str(order.id),
        client_order_id=order.client_order_id,
        side=order.side.value,
        order_type=order.order_type.value,
        time_in_force=order.time_in_force.value,
        status=order.status.value,
        quantity=int(_to_decimal(order.qty)),
        filled_quantity=int(_to_decimal(order.filled_qty)),
        filled_price=_to_decimal(order.filled_avg_price),
        stop_price=_to_decimal(order.stop_price),
        limit_price=_to_decimal(order.limit_price),
        legs=tuple(_to_broker_order(leg) for leg in order.legs or []),
    )

def _error_message(error: APIError) -> str:
    """Return Alpaca's message, or the raw error text when the body isn't JSON"""
    try:
        return error.message
    except (ValueError, KeyError, TypeError):
        return str(error)

def _translate(error: Exception) -> BrokerError:
    """Turn an alpaca-py or requests error into the BrokerError the caller should act on"""
    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return BrokerUnavailable(f"No answer from Alpaca: {error}")
    status_code = error.status_code
    message = _error_message(error)
    if status_code is None or status_code == 429 or status_code >= 500:
        return BrokerUnavailable(f"Alpaca answered {status_code}: {message}")
    if status_code == 422 and DUPLICATE_MESSAGE in message:
        return DuplicateOrder(message)
    if 400 <= status_code <= 499:
        return OrderRejected(message)
    return BrokerUnavailable(f"Alpaca answered {status_code}: {message}")

class AlpacaBroker:
    """Places, finds and cancels orders on one Alpaca account

    Every method raises a BrokerError subclass instead of alpaca-py's or requests' errors,
    so callers never import alpaca-py.
    """

    def __init__(self, trading_client):
        """Wrap a TradingClient built by alpaca_client.create_alpaca_trading_client"""
        self.client = trading_client

    def _call(self, method, *args):
        """Run one alpaca-py call and translate its errors"""
        try:
            return method(*args)
        except (APIError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as error:
            raise _translate(error) from error

    def submit_bracket_buy(self, client_order_id: str, ticker: str, quantity: int, time_in_force: str,
                           stop_price: Decimal, target_price: Decimal) -> BrokerOrder:
        """Send a market buy with a stop-loss leg and a take-profit leg

        Prices must already be rounded to Alpaca's ticks.

        Parameters:
            client_order_id (str): The bot's ID for the buy, the same on every retry
            ticker (str): The ticker symbol
            quantity (int): Shares to buy, above 0
            time_in_force (str): "day" or "gtc"; the legs use the same
            stop_price (Decimal): Where the stop-loss leg sells
            target_price (Decimal): Where the take-profit leg sells

        Returns:
            Alpaca's version of the buy, with its two legs

        Raises:
            OrderRejected, DuplicateOrder or BrokerUnavailable
        """
        request = MarketOrderRequest(
            symbol=ticker,
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce(time_in_force),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=float(target_price)),
            stop_loss=StopLossRequest(stop_price=float(stop_price)),
            client_order_id=client_order_id,
        )
        return _to_broker_order(self._call(self.client.submit_order, request))

    def submit_market_sell(self, client_order_id: str, ticker: str, quantity: int,
                           time_in_force: str) -> BrokerOrder:
        """Send a plain market sell

        Parameters:
            client_order_id (str): The bot's ID for the sell, the same on every retry
            ticker (str): The ticker symbol
            quantity (int): Shares to sell, above 0
            time_in_force (str): "day" or "gtc"

        Returns:
            Alpaca's version of the sell

        Raises:
            OrderRejected, DuplicateOrder or BrokerUnavailable
        """
        request = MarketOrderRequest(
            symbol=ticker,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce(time_in_force),
            client_order_id=client_order_id,
        )
        return _to_broker_order(self._call(self.client.submit_order, request))

    def find_order(self, client_order_id: str) -> BrokerOrder | None:
        """Look an order up by the bot's ID, with its legs

        Parameters:
            client_order_id (str): The bot's ID for the order

        Returns:
            Alpaca's version of the order, or None if Alpaca has no order with that ID

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        try:
            found = self._call(self.client.get_order_by_client_id, client_order_id)
        except OrderRejected as error:
            if error.__cause__.status_code == 404:
                return None
            raise BrokerUnavailable(f"Lookup of {client_order_id} refused: {error}") from error
        nested = GetOrderByIdRequest(nested=True)
        return _to_broker_order(self._call(self.client.get_order_by_id, found.id, nested))

    def get_order(self, alpaca_order_id: str) -> BrokerOrder | None:
        """Look an order up by Alpaca's ID

        Parameters:
            alpaca_order_id (str): Alpaca's ID for the order (a bracket leg has its own)

        Returns:
            Alpaca's version of the order, or None if Alpaca has no order with that ID

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        try:
            return _to_broker_order(self._call(self.client.get_order_by_id, alpaca_order_id))
        except OrderRejected as error:
            if error.__cause__.status_code == 404:
                return None
            raise BrokerUnavailable(f"Lookup of {alpaca_order_id} refused: {error}") from error

    def get_fill_activities(self, since: datetime) -> list:
        """Return every FILL account activity after a time, oldest first, reading every page

        alpaca-py has no method for activities, so this calls the REST endpoint through the client.

        Parameters:
            since (datetime): Naive UTC; only fills after this time

        Returns:
            A list of Alpaca's activity dicts, e.g. {"id": "20261030134220960::7f05...", "order_id": ...,
            "side": "buy", "qty": "1", "price": "755.22", "cum_qty": "1", "leaves_qty": "0", ...}

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        params = {"after": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "direction": "asc", "page_size": ACTIVITY_PAGE_SIZE}
        activities = []
        while True:
            try:
                page = self._call(self.client.get, "/account/activities/FILL", params)
            except OrderRejected as error:
                raise BrokerUnavailable(f"Activities refused: {error}") from error
            activities += page
            if len(page) < ACTIVITY_PAGE_SIZE:
                return activities
            params = {**params, "page_token": page[-1]["id"]}

    def get_account(self) -> BrokerAccount:
        """Return the account's equity now, its equity at yesterday's close and its buying power

        Returns:
            A BrokerAccount

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        try:
            account = self._call(self.client.get_account)
        except OrderRejected as error:
            raise BrokerUnavailable(f"Account lookup refused: {error}") from error
        return BrokerAccount(equity=_to_decimal(account.equity), last_equity=_to_decimal(account.last_equity),
                             buying_power=_to_decimal(account.buying_power))

    def get_positions(self) -> dict:
        """Return how many shares Alpaca holds of each ticker, for the whole account

        Fractional shares (only possible from manual trades) are cut to whole shares, so a sell never asks
        for more than Alpaca holds.

        Returns:
            {ticker: shares as an int}; empty if nothing is held

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        try:
            positions = self._call(self.client.get_all_positions)
        except OrderRejected as error:
            raise BrokerUnavailable(f"Positions lookup refused: {error}") from error
        return {position.symbol: int(_to_decimal(position.qty)) for position in positions}

    def get_tradable_tickers(self) -> set:
        """Return every US stock Alpaca can trade right now (one call, a few thousand symbols)

        Returns:
            A set of ticker symbols

        Raises:
            BrokerUnavailable if Alpaca can't be asked
        """
        request = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
        try:
            assets = self._call(self.client.get_all_assets, request)
        except OrderRejected as error:
            raise BrokerUnavailable(f"Asset lookup refused: {error}") from error
        return {asset.symbol for asset in assets if asset.tradable}

    def cancel_order(self, alpaca_order_id: str):
        """Cancel one open order

        Parameters:
            alpaca_order_id (str): Alpaca's ID for the order

        Raises:
            OrderRejected if Alpaca won't cancel it (e.g. already filled), or BrokerUnavailable
        """
        self._call(self.client.cancel_order_by_id, alpaca_order_id)
