"""
notifications
Send messages to Discord: configure once at startup, then send(kind, message, asset)
"""

#Standard Library
from pathlib import Path
import time

#Third Party Libraries
import requests

#Local Imports
from config.constants import PROCESSES
from logger import LOG_DIR, health_log
from notifications.failed import FailedLog
from notifications.routing import ASSET_KINDS, ASSETS, BOT_KINDS, check_routes, feed
from notifications.sender import Notifier

_notifier = Notifier()

def configure(environment: str, token: str | None, routes: dict, *, process: str, log_dir: Path = LOG_DIR,
              http_post=requests.post, sleep=time.sleep) -> list:
    """Set up routing for this process; called once at startup, never on import

    Bad entries are left out and the rest still work. Each problem is logged and one critical alert lists them;
    the caller records them in bot_events. Parts that can't be posted are saved to
    <log_dir>/notifications_failed_<process>.log for retry_failed.

    Parameters:
        environment (str): "live", "paper" or "dev"
        token (str | None): The Discord bot token; None or empty sends critical through the webhook and logs the rest
        routes (dict): DISCORD_ROUTES
        process (str): One of PROCESSES ("bot", "fill_stream"); an unknown one saves no failed messages
        log_dir (Path): Folder for the failed-message file
        http_post: requests.post or a fake
        sleep: time.sleep or a fake

    Returns:
        A list of problem strings, empty when the whole table is good
    """
    global _notifier
    clean, problems = check_routes(routes)
    if environment not in clean:
        problems.append(f"No routes for environment {environment!r}. Expected one of {sorted(clean)}; critical goes "
                        f"through the webhook and the rest is only logged")
    failed_log = None
    if process in PROCESSES:
        failed_log = FailedLog(Path(log_dir) / f"notifications_failed_{process}.log")
    else:
        problems.append(f"Unknown process {process!r}. Expected one of {list(PROCESSES)}; failed messages aren't "
                        f"saved for resending")
    _notifier = Notifier(environment=environment, token=token, routes=clean, http_post=http_post, sleep=sleep,
                         failed_log=failed_log)
    for problem in problems:
        health_log.warning(f"Discord routing: {problem}")
    if problems:
        _notifier.send("critical", "Discord routing has problems; these entries are skipped:\n" + "\n".join(problems))
    return problems

def send(kind: str, message: str, asset: str | None = None) -> bool:
    """Send one message to the channel for its kind (and asset); never raises

    Parameters:
        kind (str): One of BOT_KINDS or ASSET_KINDS
        message (str): The text; secrets are masked before it leaves
        asset (str | None): One of ASSETS for a per-asset kind

    Returns:
        True when posted, False when only logged or posting failed
    """
    return _notifier.send(kind, message, asset)

def retry_failed() -> int:
    """Resend saved parts that couldn't be posted (call every minute); never raises

    Returns:
        How many parts were resent
    """
    return _notifier.retry_failed()

def report_failed() -> int:
    """Send one critical line on what's still unsent and rotate the day's file (call at NOTIFY_FAILED_REPORT_TIME)

    Returns:
        How many parts were still unsent
    """
    return _notifier.report_failed()

def send_critical(message: str) -> bool:
    """Send an act-now message (old helper, kept until the old modules are gone)"""
    return send("critical", message)

def send_routine(message: str) -> bool:
    """Send a routine message (old helper, kept until the old modules are gone)"""
    return send("routine", message)

def send_trades(message: str) -> bool:
    """Send an old module's trade message to routine; new code uses send("trades", ..., asset)"""
    return send("routine", message)
