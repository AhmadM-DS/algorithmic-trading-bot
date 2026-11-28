"""
logger.py
Create a general logging structure.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
import os
from config.settings import MASK_ENV_VARS

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)-8s %(module)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
formatter.converter = time.gmtime

def redact(text):
    for name in MASK_ENV_VARS:
        value = os.environ.get(name)
        if value and value in text:
            text = text.replace(value, "********")
    return text

class RedactFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        record.args = None
        record.msg = redact(message)
        if record.exc_info:
            record.exc_text = redact(formatter.formatException(record.exc_info))
        return True

mask_filter = RedactFilter()
error_handler = RotatingFileHandler(LOG_DIR / "errors.log", maxBytes=5000000, backupCount=3)
error_handler.setLevel(logging.WARNING)
error_handler.setFormatter(formatter)
error_handler.addFilter(mask_filter)
# On the root logger so it catches warnings from our loggers (they propagate up) and from libraries.
logging.getLogger().addHandler(error_handler)

def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        log_path = LOG_DIR / f"{name}.log"
        logger.setLevel(logging.INFO)

        handler = RotatingFileHandler(log_path, maxBytes=5000000, backupCount=3)
        handler.setFormatter(formatter)
        handler.addFilter(mask_filter)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.addFilter(mask_filter)

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

class ChangeLog:
    """Log a problem once when it starts and once when it ends, per key, never on every check (alert on change)"""

    def __init__(self, log):
        self.log = log
        self.failing = set()

    def __contains__(self, key) -> bool:
        return key in self.failing

    def failed(self, key, message: str) -> bool:
        """Log message as a warning if key wasn't failing yet; return True when this call logged"""
        if key in self.failing:
            return False
        self.log.warning(message)
        self.failing.add(key)
        return True

    def recovered(self, key, message: str) -> bool:
        """Log message as info if key was failing; return True when this call logged"""
        if key not in self.failing:
            return False
        self.log.info(message)
        self.failing.discard(key)
        return True

    def clear(self):
        """Forget every failure, so each is logged again the next time"""
        self.failing.clear()

# Temporary: old modules log here until they are rewritten. Delete once nothing imports it.
legacy_log = get_logger("legacy")