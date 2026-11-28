"""
sender.py
Send one message to its Discord channel with the bot token, falling back to the critical webhook or the log, and
resend what couldn't be posted
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
import time
from zoneinfo import ZoneInfo

#Third Party Libraries
import requests

#Local Imports
from config.constants import (DISCORD_API_BASE, DISCORD_MAX_MESSAGE_CHARS, DISCORD_MAX_RETRY_SECONDS,
                              DISCORD_MENTION, DISCORD_TIMEOUT_SECONDS, MARKET_TIME_ZONE, NOTIFY_RETRY_BATCH)
from logger import ChangeLog, health_log, redact, routine_log
from notifications.discord import PostFailure, post_message, split_message
from notifications.failed import FailedLog
from notifications.routing import resolve

CRITICAL = "critical"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

@dataclass(frozen=True)
class Target:
    """One way to post a message: via is "bot" or "webhook"; headers is None for a webhook"""
    via: str
    url: str
    headers: dict | None

def _utc_now() -> datetime:
    """Return the current time in UTC"""
    return datetime.now(timezone.utc)

def _delay_marker(failed_at: datetime) -> str:
    """Return the prefix a resent part carries, e.g. "(delayed, first failed Nov 27 10:32 ET) " """
    local = failed_at.astimezone(ZoneInfo(MARKET_TIME_ZONE))
    return f"(delayed, first failed {MONTHS[local.month - 1]} {local.day} {local:%H:%M} ET) "

PART_LIMIT = DISCORD_MAX_MESSAGE_CHARS - len(_delay_marker(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)))

class Notifier:
    """Holds one process's routing setup; no method raises

    Each message has an ordered list of targets: the bot (when its channel and the token are set) and, for critical
    only, the webhook (DISCORD_CRITICAL_HOOK unless hook_url is given). Targets are tried in order. No target means
    the message is only logged. A part no target could post is saved to failed_log (when there is one) and resent by
    retry_failed.
    """
    def __init__(self, environment: str | None = None, token: str | None = None, routes: dict | None = None,
                 http_post=requests.post, sleep=time.sleep, hook_url: str | None = None,
                 failed_log: FailedLog | None = None, clock=_utc_now):
        self.environment = environment
        self.table = None if routes is None else routes.get(environment)
        self.token = token or None
        self.http_post = http_post
        self.sleep = sleep
        self.hook_url = hook_url
        self.failed_log = failed_log
        self.clock = clock
        self.outages = ChangeLog(health_log)
        self.unrouted = ChangeLog(health_log)
        self.resend_lock = threading.Lock()

    def send(self, kind: str, message: str, asset: str | None = None) -> bool:
        """Send one message to the channel for its kind (and asset)

        Parameters:
            kind (str): One of routing.BOT_KINDS or routing.ASSET_KINDS
            message (str): The text; secrets are masked before it leaves
            asset (str | None): One of routing.ASSETS for a per-asset kind (see routing.feed)

        Returns:
            True when every part was posted, False when it was only logged or posting failed
        """
        try:
            return self._send(kind, message, asset)
        except Exception as error:
            health_log.error(f"Discord {kind}/{asset} not sent, unexpected {type(error).__name__}: {error}. "
                             f"Message: {message}")
            return False

    def retry_failed(self) -> int:
        """Resend saved parts: critical first, then oldest first, posting at most NOTIFY_RETRY_BATCH

        A way of posting (bot, webhook) that has an outage is skipped for the rest of the batch, which stops once
        every way is down. A part stays saved while any of its targets is down or it has no target; it's dropped
        (logged, counted in the report) only when every target refused it. One resend runs at a time.

        Returns:
            How many parts were resent
        """
        try:
            with self.resend_lock:
                return self._retry_failed()
        except Exception as error:
            health_log.error(f"Resending failed Discord messages stopped, unexpected {type(error).__name__}: {error}")
            return 0

    def report_failed(self) -> int:
        """Send one critical line saying how many parts went unsent (waiting or dropped), then rotate the day's file

        If every target fails, the line is saved to the new file; with no target at all it's only logged.

        Returns:
            How many parts were still unsent
        """
        try:
            with self.resend_lock:
                return self._report_failed()
        except Exception as error:
            health_log.error(f"Failed-message report stopped, unexpected {type(error).__name__}: {error}")
            return 0

    def _send(self, kind, message, asset):
        """Route, mark, split and post one message, saving what doesn't go out"""
        text = redact(message)
        if kind == CRITICAL and DISCORD_MENTION not in text:
            text = f"{text} {DISCORD_MENTION}"
        kind, asset, text = self._reroute(kind, asset, text)
        parts = split_message(text, PART_LIMIT)
        if not parts:
            health_log.warning(f"Empty Discord {kind} message not sent")
            return False
        targets = self._targets(kind, asset)
        if not targets:
            log = health_log.warning if kind == CRITICAL else routine_log.info
            log(f"Discord {kind} has no channel, token or webhook; logged only: {text}")
            return False
        for index, part in enumerate(parts):
            failure = self._deliver(targets, part)
            if failure:
                if self.failed_log is not None:
                    self.failed_log.save(kind, asset, parts[index:], self.clock())
                routine_log.info(f"Discord {kind} not delivered ({failure}): {text}")
                return False
        routine_log.info(f"Discord {kind}: {text}")
        return True

    def _reroute(self, kind, asset, text):
        """Send a kind or asset the table can't route to health, marked, and warn once per route. Critical keeps its
        kind: without a channel its targets are just the webhook"""
        if kind == CRITICAL or resolve(self.table, kind, asset).known:
            return kind, asset, text
        self.unrouted.failed((kind, asset), f"No Discord route for kind {kind!r}, asset {asset!r} in "
                                            f"{self.environment!r}. Sent to health instead")
        return "health", None, f"[no route: {kind}/{asset}] {text}"

    def _targets(self, kind, asset) -> list:
        """Return the targets to try in order: the bot when its channel and token are set, then the webhook for
        critical"""
        targets = []
        channel = resolve(self.table, kind, asset).channel_id
        if channel and self.token:
            targets.append(Target("bot", f"{DISCORD_API_BASE}/channels/{channel}/messages",
                                  {"Authorization": f"Bot {self.token}"}))
        hook = self.hook_url or os.environ.get("DISCORD_CRITICAL_HOOK")
        if kind == CRITICAL and hook:
            targets.append(Target("webhook", hook, None))
        return targets

    def _deliver(self, targets, part, down: set | None = None) -> PostFailure | None:
        """Post one part through the first target that takes it; return None when posted, else an outage if any target
        had one (so the part waits), or the refusal when every target refused it. Adds each way of posting that had
        an outage to down, when given"""
        failures = []
        for target in targets:
            failure = self._post(target, part)
            if failure is None:
                return None
            if failure.outage and down is not None:
                down.add(target.via)
            failures.append(failure)
        return next((failure for failure in failures if failure.outage), failures[-1] if failures else None)

    def _post(self, target, part) -> PostFailure | None:
        """Post one part to one target; an outage or recovery is logged once per way of posting"""
        failure = post_message(self.http_post, target.url, part, headers=target.headers,
                               timeout=DISCORD_TIMEOUT_SECONDS, max_retry_seconds=DISCORD_MAX_RETRY_SECONDS,
                               sleep=self.sleep)
        if failure is None:
            self.outages.recovered(target.via, f"Discord posting works again via {target.via}")
        elif failure.outage:
            self.outages.failed(target.via, f"Discord posting failed via {target.via} ({failure}). Messages are "
                                            f"saved for resending until it works again")
        return failure

    def _retry_failed(self):
        """Resend saved parts; see retry_failed"""
        if self.failed_log is None:
            return 0
        waiting = sorted(self.failed_log.pending(), key=lambda entry: (entry.kind != CRITICAL, entry.failed_at))
        ways = {target.via for target in self._targets(CRITICAL, None)} | ({"bot"} if self.token else set())
        down, attempted, resent = set(), 0, 0
        for entry in waiting:
            if attempted >= NOTIFY_RETRY_BATCH or (ways and ways <= down):
                break
            kind, asset, text = self._reroute(entry.kind, entry.asset, _delay_marker(entry.failed_at) + entry.message)
            targets = [target for target in self._targets(kind, asset) if target.via not in down]
            if not targets:
                continue
            attempted += 1
            failure = self._deliver(targets, text[:DISCORD_MAX_MESSAGE_CHARS], down)
            if failure and failure.outage:
                continue
            if failure:
                self.failed_log.mark_dropped(entry.id, str(failure))
                health_log.warning(f"Discord refused a saved {kind} message ({failure}); dropped: {text}")
                continue
            self.failed_log.mark_sent(entry.id)
            routine_log.info(f"Discord {kind} resent: {text}")
            resent += 1
        return resent

    def _report_failed(self):
        """Summarize and rotate; see report_failed"""
        if self.failed_log is None:
            return 0
        unsent = len(self.failed_log.unsent())
        rotated = self.failed_log.rotate(self.clock().astimezone(ZoneInfo(MARKET_TIME_ZONE)).date())
        if not unsent:
            return 0
        text = f"{unsent} Discord messages couldn't be delivered today; they're in {rotated.name}. {DISCORD_MENTION}"
        targets = self._targets(CRITICAL, None)
        if not targets:
            health_log.warning(f"Failed-message report has no channel, token or webhook; logged only: {text}")
            return unsent
        failure = self._deliver(targets, text)
        if failure:
            self.failed_log.save(CRITICAL, None, [text], self.clock())
            health_log.warning(f"Failed-message report not delivered ({failure}): {text}")
        return unsent
