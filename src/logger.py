"""
logger.py
Create a general logging structure.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "logs" / "trading_bot.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        handler = RotatingFileHandler(LOG_PATH, maxBytes=5000000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

        logger.addHandler(handler)
        logger.addHandler(console)
    
    return logger