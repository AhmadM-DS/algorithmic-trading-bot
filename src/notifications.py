"""
notifications.py
Send messages to a dedicated discord channel.
"""

#Standard Library
import os

#Third Party Library
from dotenv import load_dotenv
import requests

#Local imports
from logger import get_logger
logger = get_logger(__name__)

#Load environment variables
load_dotenv()
CRITICAL_HOOK = os.getenv("DISCORD_CRITICAL_HOOK")
TRADES_HOOK = os.getenv("DISCORD_TRADES_HOOK")
ROUTINE_HOOK = os.getenv("DISCORD_ROUTINE_HOOK")
if not all ([CRITICAL_HOOK, TRADES_HOOK, ROUTINE_HOOK]):
    logger.warning("One or more environment variables are missing.")

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
    return _send(CRITICAL_HOOK, message)

def send_trades(message):
    return _send(TRADES_HOOK, message)

def send_routine(message):
    return _send(ROUTINE_HOOK, message)

if __name__ == "__main__":
    print("Critical:", send_critical("testing if ping works <@375084779256676353>"))