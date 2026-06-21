"""
logger.py
Create a general logging structure.
"""

import logging
from logging.handlers import RotatingFileHandler

def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        handler = RotatingFileHandler("../logs/trading_bot.log", maxBytes=5000000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

        logger.addHandler(handler)
        logger.addHandler(console)
    
    return logger