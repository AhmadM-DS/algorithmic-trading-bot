"""
logger.py
Create a general logging structure.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)-8s %(module)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
formatter.converter = time.gmtime

error_handler = RotatingFileHandler(LOG_DIR / "errors.log", maxBytes=5000000, backupCount=3)
error_handler.setLevel(logging.WARNING)
error_handler.setFormatter(formatter)
# On the root logger so it catches warnings from our loggers (they propagate up) and from libraries.
logging.getLogger().addHandler(error_handler)

def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        log_path = LOG_DIR / f"{name}.log"
        logger.setLevel(logging.INFO)

        handler = RotatingFileHandler(log_path, maxBytes=5000000, backupCount=3)
        handler.setFormatter(formatter)

        console = logging.StreamHandler()
        console.setFormatter(formatter)

        logger.addHandler(handler)
        logger.addHandler(console)
    
    return logger

#Create loggers
trades_log = get_logger("trades")
signals_log = get_logger("signals")
audit_log = get_logger("audit")
health_log = get_logger("health")
routine_log = get_logger("routine")
db_log = get_logger("db")
api_log = get_logger("api")

# Temporary: old modules log here until they are rewritten. Delete once nothing imports it.
legacy_log = get_logger("legacy")