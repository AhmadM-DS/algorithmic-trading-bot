"""
notifications.py
Send messages to a dedicated discord channel.
"""

#Standard Library
import os

#Third Party Library
import requests

#Local imports
from logger import get_logger
logger = get_logger(__name__)

def _send(url, message):
    try:
        r = requests.post(url, json={"content": message}, timeout=10)
        if r.ok:
            logger.info(f"Successfully sent message to Discord: {message}")
            return True
        else:
            logger.warning(f"Raised Status Code {r.status_code} for {message}.")
            return False
    except requests.exceptions.RequestException:
        logger.error(f"Notification not sent to Discord: {message}")
        return False

def send_critical(message):
    return _send(os.environ["DISCORD_CRITICAL_HOOK"], message)

def send_trades(message):
    return _send(os.environ["DISCORD_TRADES_HOOK"], message)

def send_routine(message):
    return _send(os.environ["DISCORD_ROUTINE_HOOK"], message)