"""
temp_order_testing.py
Manual end-to-end test cases for order placement: Alpaca fill, TradingBot database, and Discord notifications.
"""

#Standard Library
import time
from pathlib import Path

#Third Party Library
from dotenv import load_dotenv

#Local imports
from logger import get_logger
logger = get_logger(__name__)

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from alpaca_client import api, tradeapi
from trader import place_market_order, has_position, sync_order_statuses
from db import get_connection, insert_order, get_open_orders, update_order_status
from notifications import send_trades, send_routine, send_critical
from market_hours import is_market_open

TEST_TICKER = "AAPL"
INVALID_TICKER = "NOTAREALTICKER123"


def _poll_order(order_id, timeout=15, interval=2):
    """
    Poll Alpaca for an order's latest state until it stops being open or the timeout elapses.

    Parameters:
        order_id (str): The Alpaca order id to poll.
        timeout (int): Max seconds to wait.
        interval (int): Seconds between polls.
    """
    waited = 0
    order = api.get_order(order_id)
    while order.status in ("new", "pending_new", "accepted") and waited < timeout:
        time.sleep(interval)
        waited += interval
        order = api.get_order(order_id)
    return order


def test_valid_market_buy():
    """Place a normal market buy order and confirm Alpaca accepts it, Discord fires, and the DB records it."""
    logger.info("=== TEST: valid market buy ===")
    result = place_market_order(TEST_TICKER, 1, "buy")
    if "Order Placed" not in result:
        logger.error(f"FAIL: expected order to be placed, got {result}")
        return False

    order = result["Order Placed"]
    filled = _poll_order(order.id)
    logger.info(f"Alpaca order {order.id} status after poll: {filled.status}")

    with get_connection() as conn:
        price = filled.filled_avg_price or 0
        new_id = insert_order(conn, filled.id, TEST_TICKER, "buy", 1, price, filled.status)
        logger.info(f"Inserted test order as TradingBot.Orders row {new_id}")

    logger.info("PASS: valid market buy placed, polled, and written to DB. Check Alpaca dashboard and #trades Discord channel to confirm.")
    return True


def test_valid_market_sell_with_position():
    """Sell back a share only if a position actually exists, exercising the real sell path."""
    logger.info("=== TEST: valid market sell (requires existing position) ===")
    if not has_position(TEST_TICKER):
        logger.warning(f"SKIP: no open position in {TEST_TICKER} to sell.")
        return None

    result = place_market_order(TEST_TICKER, 1, "sell")
    if "Order Placed" not in result:
        logger.error(f"FAIL: expected sell order to be placed, got {result}")
        return False

    order = result["Order Placed"]
    filled = _poll_order(order.id)
    with get_connection() as conn:
        price = filled.filled_avg_price or 0
        insert_order(conn, filled.id, TEST_TICKER, "sell", 1, price, filled.status)

    logger.info("PASS: valid market sell placed and written to DB.")
    return True


def test_sell_without_position():
    """Confirm has_position() blocks a sell on a ticker with no open position, before an order is ever submitted."""
    logger.info("=== TEST: sell without a position is blocked ===")
    if has_position(INVALID_TICKER):
        logger.error("FAIL: has_position() unexpectedly returned True for a ticker that should have no position.")
        return False
    logger.info("PASS: has_position() correctly reported no position; trade would be blocked before submission.")
    return True


def test_invalid_ticker():
    """A nonexistent symbol should be rejected by Alpaca and hit the 'Order Failed' branch."""
    logger.info("=== TEST: invalid ticker symbol ===")
    result = place_market_order(INVALID_TICKER, 1, "buy")
    if "Order Failed" not in result:
        logger.error(f"FAIL: expected order to fail for invalid ticker, got {result}")
        return False
    logger.info(f"PASS: invalid ticker correctly rejected. Reason: {result['Order Failed']}")
    return True


def test_invalid_quantity_zero():
    """A zero quantity should be rejected by Alpaca."""
    logger.info("=== TEST: invalid quantity (zero) ===")
    result = place_market_order(TEST_TICKER, 0, "buy")
    if "Order Failed" not in result:
        logger.error(f"FAIL: expected order to fail for zero quantity, got {result}")
        return False
    logger.info(f"PASS: zero quantity correctly rejected. Reason: {result['Order Failed']}")
    return True


def test_invalid_quantity_negative():
    """A negative quantity should be rejected by Alpaca."""
    logger.info("=== TEST: invalid quantity (negative) ===")
    result = place_market_order(TEST_TICKER, -5, "buy")
    if "Order Failed" not in result:
        logger.error(f"FAIL: expected order to fail for negative quantity, got {result}")
        return False
    logger.info(f"PASS: negative quantity correctly rejected. Reason: {result['Order Failed']}")
    return True


def test_oversized_order():
    """A quantity far beyond available buying power should fail with an Alpaca insufficient-funds error."""
    logger.info("=== TEST: oversized order (insufficient buying power) ===")
    result = place_market_order(TEST_TICKER, 1_000_000, "buy")
    if "Order Failed" not in result:
        logger.error(f"FAIL: expected order to fail for oversized quantity, got {result}")
        return False
    logger.info(f"PASS: oversized order correctly rejected. Reason: {result['Order Failed']}")
    return True


def test_fractional_quantity():
    """Fractional share orders are not supported by place_market_order's integer-oriented wrapper; confirm Alpaca's own response."""
    logger.info("=== TEST: fractional quantity ===")
    result = place_market_order(TEST_TICKER, 0.5, "buy")
    if "Order Placed" in result:
        order = result["Order Placed"]
        filled = _poll_order(order.id)
        with get_connection() as conn:
            price = filled.filled_avg_price or 0
            insert_order(conn, filled.id, TEST_TICKER, "buy", 0.5, price, filled.status)
        logger.info("PASS: fractional order accepted, polled, and written to DB.")
        return True
    logger.info(f"PASS (fractional not supported on this account): {result.get('Order Failed')}")
    return True


def test_db_write_and_read_roundtrip():
    """Directly exercise insert_order/get_open_orders/update_order_status against TradingBot without touching Alpaca."""
    logger.info("=== TEST: DB insert/read/update roundtrip ===")
    fake_order_id = f"TEST-{int(time.time())}"
    with get_connection() as conn:
        new_id = insert_order(conn, fake_order_id, TEST_TICKER, "buy", 1, 100.00, "new")
        open_orders = get_open_orders(conn)
        if not any(row[0] == fake_order_id for row in open_orders):
            logger.error("FAIL: inserted test order not found via get_open_orders().")
            return False

        update_order_status(conn, fake_order_id, "filled")
        open_orders_after = get_open_orders(conn)
        if any(row[0] == fake_order_id for row in open_orders_after):
            logger.error("FAIL: order still shows as open after status update to 'filled'.")
            return False

    logger.info(f"PASS: DB roundtrip succeeded for row {new_id} (Alpaca_Order_ID={fake_order_id}).")
    return True


def test_sync_order_statuses():
    """Run the real sync_order_statuses() job and confirm it doesn't error against live open orders."""
    logger.info("=== TEST: sync_order_statuses against live open orders ===")
    try:
        with get_connection() as conn:
            sync_order_statuses(conn)
        logger.info("PASS: sync_order_statuses() ran without error. Check TradingBot.Orders for updated statuses.")
        return True
    except Exception as e:
        logger.error(f"FAIL: sync_order_statuses() raised {e}")
        return False


def test_discord_channels():
    """Fire one distinguishable message per Discord webhook and confirm each request succeeded."""
    logger.info("=== TEST: Discord notification channels ===")
    stamp = int(time.time())
    results = {
        "trades": send_trades(f"[TEST {stamp}] trades channel check"),
        "routine": send_routine(f"[TEST {stamp}] routine channel check"),
        "critical": send_critical(f"[TEST {stamp}] critical channel check"),
    }
    if not all(results.values()):
        logger.error(f"FAIL: one or more Discord channels did not accept the message: {results}")
        return False
    logger.info(f"PASS: all three Discord channels accepted test messages (stamp={stamp}). Confirm they appeared in Discord.")
    return True


def main():
    if not is_market_open():
        logger.warning("Market is currently closed. Orders will likely stay in 'accepted' status instead of filling.")

    tests = [
        test_db_write_and_read_roundtrip,
        test_discord_channels,
        test_sell_without_position,
        test_invalid_ticker,
        test_invalid_quantity_zero,
        test_invalid_quantity_negative,
        test_oversized_order,
        test_fractional_quantity,
        test_valid_market_buy,
        test_valid_market_sell_with_position,
        test_sync_order_statuses,
    ]

    results = {}
    for test in tests:
        try:
            results[test.__name__] = test()
        except Exception as e:
            logger.exception(f"{test.__name__} raised an unexpected exception: {e}")
            results[test.__name__] = False

    logger.info("=== SUMMARY ===")
    for name, outcome in results.items():
        label = "SKIPPED" if outcome is None else ("PASS" if outcome else "FAIL")
        logger.info(f"{label}: {name}")

    logger.info("Manual verification still required: confirm test orders/fills on the Alpaca paper dashboard "
                "and confirm messages landed in the #trades/#routine/#critical Discord channels.")


if __name__ == "__main__":
    main()
