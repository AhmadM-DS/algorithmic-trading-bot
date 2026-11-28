"""
test_notifications_failed.py
Unit tests for D6: the failed-message log, the resend every minute and the end-of-day summary, with a fake Discord
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone
import json
import logging
import threading
import time

#Third Party Libraries
import pytest

#Local Imports
import notifications
from config.constants import DISCORD_MAX_MESSAGE_CHARS, NOTIFY_RETRY_BATCH
from notifications.failed import FailedLog
from notifications.sender import Notifier

CRITICAL = "100000000000000001"
HEALTH = "100000000000000002"
ROUTINE = "100000000000000003"
HOOK = "https://discord.com/api/webhooks/1/fake"
ROUTES = {"paper": {"critical": CRITICAL, "health": HEALTH, "routine": ROUTINE, "audit": None}}

FAILED_AT = datetime(2026, 11, 27, 15, 32, tzinfo=timezone.utc)
"""10:32 in New York"""

class FakeResponse:
    """Just enough of a requests.Response: a status and a JSON body"""
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.body = body

    def json(self):
        return self.body

class FakeDiscord:
    """Answer 503 while down, 200 otherwise, and record every call"""
    def __init__(self, down=False):
        self.down = down
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "content": json["content"]})
        return FakeResponse(503 if self.down else 200)

    def contents(self):
        return [call["content"] for call in self.calls]

    def channels(self):
        return [call["url"].split("/channels/")[1].split("/")[0] if "/channels/" in call["url"] else "webhook"
                for call in self.calls]

class FakeClock:
    """A UTC clock the test sets by hand"""
    def __init__(self, now=FAILED_AT):
        self.now = now

    def __call__(self):
        return self.now

@pytest.fixture
def log_path(tmp_path):
    """Where this test's failed-message log lives"""
    return tmp_path / "notifications_failed_bot.log"

def notifier(discord, log_path, clock=None, token="bot-token", routes=ROUTES):
    """Build a Notifier on the fake Discord that saves failed messages to log_path"""
    return Notifier(environment="paper", token=token, routes=routes, http_post=discord, sleep=lambda s: None,
                    hook_url=HOOK, failed_log=FailedLog(log_path), clock=clock or FakeClock())

def lines(log_path) -> list:
    """Return the log file's lines as parsed JSON"""
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

def test_saved_part_is_one_json_line(log_path):
    """Save each part as one JSON line with an id, the UTC time, kind, asset and text"""
    failed = FailedLog(log_path)

    failed.save("trades", "day", ["Bought AAPL"], FAILED_AT)

    [line] = lines(log_path)
    assert (line["failed_at"], line["kind"], line["asset"], line["message"]) == \
           ("2026-11-27T15:32:00+00:00", "trades", "day", "Bought AAPL")
    assert line["id"]

def test_sent_line_marks_a_part_done_without_rewriting(log_path):
    """Mark a resent part with a new sent line; the failed line stays"""
    failed = FailedLog(log_path)
    failed.save("routine", None, ["one", "two"], FAILED_AT)
    first = failed.pending()[0]

    failed.mark_sent(first.id)

    assert [entry.message for entry in failed.pending()] == ["two"]
    assert len(lines(log_path)) == 3

def test_pending_is_rebuilt_after_a_restart(log_path):
    """Read what's still waiting from the file, so a restart loses nothing"""
    FailedLog(log_path).save("critical", None, ["Kill switch on"], FAILED_AT)

    pending = FailedLog(log_path).pending()

    assert [(entry.kind, entry.message, entry.failed_at) for entry in pending] == \
           [("critical", "Kill switch on", FAILED_AT)]

def test_bad_line_is_skipped_and_logged_once(log_path, caplog):
    """Skip a line that can't be read, keep the rest, and log it once"""
    failed = FailedLog(log_path)
    failed.save("routine", None, ["before"], FAILED_AT)
    with log_path.open("a", encoding="utf-8") as file:
        file.write('{"id": "broken", "kind": \n')
        file.write('["not", "a", "record"]\n')
    failed.save("routine", None, ["after"], FAILED_AT)

    with caplog.at_level(logging.WARNING, logger="health"):
        first, second = failed.pending(), failed.pending()

    assert [entry.message for entry in first] == ["before", "after"] == [entry.message for entry in second]
    assert caplog.text.count("Unreadable line") == 2

def test_no_file_means_nothing_pending(log_path):
    """Report nothing waiting before anything failed"""

    pending = FailedLog(log_path).pending()

    assert pending == []

def test_rotate_renames_with_the_day(log_path):
    """Move the day's file aside under its New York date, leaving nothing pending"""
    failed = FailedLog(log_path)
    failed.save("routine", None, ["one"], FAILED_AT)

    rotated = failed.rotate(date(2026, 11, 27))

    assert rotated.name == "notifications_failed_bot.log.2026-11-27"
    assert (log_path.exists(), failed.pending()) == (False, [])

def test_second_rotate_the_same_day_keeps_the_first(log_path):
    """Never overwrite an earlier rotated file of the same day"""
    failed = FailedLog(log_path)
    failed.save("routine", None, ["one"], FAILED_AT)
    failed.rotate(date(2026, 11, 27))
    failed.save("routine", None, ["two"], FAILED_AT)

    rotated = failed.rotate(date(2026, 11, 27))

    assert rotated.name == "notifications_failed_bot.log.2026-11-27-2"

def test_rotate_without_a_file_does_nothing(log_path):
    """Return None when there's no file to rotate"""

    rotated = FailedLog(log_path).rotate(date(2026, 11, 27))

    assert rotated is None

def test_failed_post_saves_the_failed_part_and_the_rest(log_path):
    """Save only the parts that didn't go out, starting at the one that failed"""
    discord = FakeDiscord()
    sender = notifier(discord, log_path)
    answers = iter([FakeResponse(200), FakeResponse(503)])
    sender.http_post = lambda url, **kwargs: next(answers)
    text = "\n".join(["x" * 1500, "y" * 1500, "z" * 1500])

    sender.send("routine", text)

    assert [line["message"] for line in lines(log_path)] == ["y" * 1500, "z" * 1500]

def test_logged_only_message_is_not_saved(log_path):
    """Save nothing for a kind whose channel isn't set up: it was never meant to be posted"""
    sender = notifier(FakeDiscord(), log_path)

    sender.send("audit", "Audit passed")

    assert not log_path.exists()

def test_unknown_route_is_saved_under_health(log_path):
    """Save a misrouted message as it was sent: to health, with its marker"""
    sender = notifier(FakeDiscord(down=True), log_path)

    sender.send("critcal", "Kill switch on")

    [line] = lines(log_path)
    assert (line["kind"], line["message"]) == ("health", "[no route: critcal/None] Kill switch on")

def test_resend_marks_the_delay_and_the_line_sent(log_path):
    """Resend a failed message marked with when it first failed (New York time), then never again"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "Market is open")
    discord.down = False

    first, second = sender.retry_failed(), sender.retry_failed()

    assert (first, second) == (1, 0)
    assert discord.contents()[-1] == "(delayed, first failed Nov 27 10:32 ET) Market is open"

def test_critical_is_resent_before_older_messages(log_path):
    """Resend critical first, then the rest oldest first"""
    discord = FakeDiscord(down=True)
    clock = FakeClock()
    sender = notifier(discord, log_path, clock=clock)
    sender.send("routine", "older routine")
    clock.now += timedelta(minutes=1)
    sender.send("health", "newer health")
    clock.now += timedelta(minutes=1)
    sender.send("critical", "newest critical")
    discord.down, discord.calls = False, []

    sender.retry_failed()

    assert discord.channels() == [CRITICAL, ROUTINE, HEALTH]

def test_resend_stops_at_the_first_failure(log_path):
    """Stop resending while Discord still refuses, and keep everything pending"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "one")
    sender.send("routine", "two")
    discord.calls = []

    resent = sender.retry_failed()

    assert (resent, len(discord.calls), len(sender.failed_log.pending())) == (0, 1, 2)

def test_rejected_message_doesnt_block_the_rest(log_path):
    """Drop a message Discord refuses on its own (400) and resend the ones after it; only an outage stops the batch"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "rejected one")
    sender.send("routine", "good one")
    answers = iter([FakeResponse(400), FakeResponse(200)])
    sender.http_post = lambda url, **kwargs: next(answers)

    resent = sender.retry_failed()

    assert (resent, sender.failed_log.pending()) == (1, [])
    assert [entry.message for entry in sender.failed_log.dropped()] == ["rejected one"]

def test_failed_resend_is_not_saved_again(log_path):
    """Keep one line per message: a resend that fails adds nothing"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "one")

    sender.retry_failed()

    assert len(lines(log_path)) == 1

def test_resend_is_capped_per_call(log_path):
    """Resend at most NOTIFY_RETRY_BATCH messages per minute, so the backlog can't trip a rate limit"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    for i in range(NOTIFY_RETRY_BATCH + 3):
        sender.send("routine", f"message {i}")
    discord.down = False

    resent = sender.retry_failed()

    assert (resent, len(sender.failed_log.pending())) == (NOTIFY_RETRY_BATCH, 3)

def test_resend_after_a_restart(log_path):
    """Resend what an earlier run saved"""
    discord = FakeDiscord(down=True)
    notifier(discord, log_path).send("routine", "before restart")
    discord.down = False

    resent = notifier(discord, log_path).retry_failed()

    assert resent == 1

def test_resend_skips_a_kind_no_longer_set_up(log_path):
    """Leave a message pending when its channel isn't set up any more, and resend the others"""
    discord = FakeDiscord(down=True)
    notifier(discord, log_path).send("routine", "routine one")
    notifier(discord, log_path).send("health", "health one")
    discord.down = False
    sender = notifier(discord, log_path, routes={"paper": {"critical": CRITICAL, "health": HEALTH, "routine": None}})

    resent = sender.retry_failed()

    assert (resent, [entry.message for entry in sender.failed_log.pending()]) == (1, ["routine one"])

def test_resend_never_raises(log_path, monkeypatch):
    """Return 0 instead of raising when reading the log fails unexpectedly"""
    sender = notifier(FakeDiscord(), log_path)
    monkeypatch.setattr(sender.failed_log, "pending", lambda: 1 / 0)

    resent = sender.retry_failed()

    assert resent == 0

def test_every_saved_part_fits_with_its_marker(log_path):
    """Leave room in every part for the delay marker, so a resend is never over Discord's limit"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "\n".join("w" * 1999 for _ in range(3)))
    discord.down, discord.calls = False, []

    sender.retry_failed()

    assert discord.calls and all(len(content) <= DISCORD_MAX_MESSAGE_CHARS for content in discord.contents())

def test_report_sends_one_summary_and_rotates(log_path):
    """Send one critical line naming how many messages are still waiting and where, then start a new file"""
    discord = FakeDiscord(down=True)
    clock = FakeClock(datetime(2026, 11, 27, 21, 30, tzinfo=timezone.utc))
    sender = notifier(discord, log_path, clock=clock)
    sender.send("routine", "one")
    sender.send("routine", "two")
    discord.down, discord.calls = False, []

    waiting = sender.report_failed()

    assert waiting == 2
    assert discord.channels() == [CRITICAL]
    assert "2 Discord messages couldn't be delivered" in discord.contents()[0]
    assert "notifications_failed_bot.log.2026-11-27" in discord.contents()[0]
    assert sender.failed_log.pending() == []

def test_report_with_nothing_waiting_sends_nothing(log_path):
    """Send no summary when every message went out, but still rotate the day's file"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "one")
    discord.down = False
    sender.retry_failed()
    discord.calls = []

    waiting = sender.report_failed()

    assert (waiting, discord.calls, log_path.exists()) == (0, [], False)

def test_report_uses_the_webhook_when_the_bot_fails(log_path):
    """Send the summary through the webhook when the bot's post fails, and don't save it twice"""
    sender = notifier(FakeDiscord(), log_path)
    sender.failed_log.save("routine", None, ["one"], FAILED_AT)
    calls = []

    def bot_down_webhook_up(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(503 if "/channels/" in url else 200)

    sender.http_post = bot_down_webhook_up

    sender.report_failed()

    assert calls[-1] == HOOK
    assert sender.failed_log.pending() == []

def test_report_that_cant_be_sent_is_saved_for_resend(log_path):
    """Save the summary to the new file when neither the bot nor the webhook can post it"""
    sender = notifier(FakeDiscord(down=True), log_path)
    sender.failed_log.save("routine", None, ["one"], FAILED_AT)

    sender.report_failed()

    assert [entry.kind for entry in sender.failed_log.pending()] == ["critical"]

def test_configure_saves_failed_messages_per_process(monkeypatch, tmp_path):
    """Save each process's failed messages in its own file in the log folder"""
    monkeypatch.setattr(notifications, "_notifier", notifications._notifier)
    discord = FakeDiscord(down=True)
    notifications.configure("paper", "bot-token", ROUTES, process="fill_stream", log_dir=tmp_path,
                            http_post=discord, sleep=lambda s: None)

    notifications.send("routine", "one")

    assert (tmp_path / "notifications_failed_fill_stream.log").exists()

def test_configure_reports_an_unknown_process(monkeypatch, tmp_path):
    """Report a process other than bot and fill_stream, and save no failed messages"""
    monkeypatch.setattr(notifications, "_notifier", notifications._notifier)
    discord = FakeDiscord(down=True)

    problems = notifications.configure("paper", "bot-token", ROUTES, process="screener", log_dir=tmp_path,
                                       http_post=discord, sleep=lambda s: None)
    notifications.send("routine", "one")

    assert len(problems) == 1
    assert list(tmp_path.iterdir()) == []

def test_unsent_holds_waiting_and_dropped_parts(log_path):
    """Return every part that never went out, waiting or dropped, but not the resent ones"""
    failed = FailedLog(log_path)
    failed.save("routine", None, ["sent", "dropped", "waiting"], FAILED_AT)
    sent, dropped, _ = failed.pending()
    failed.mark_sent(sent.id)
    failed.mark_dropped(dropped.id, "status 400")

    unsent = failed.unsent()

    assert [entry.message for entry in unsent] == ["dropped", "waiting"]

def test_report_counts_dropped_messages(log_path):
    """Count messages Discord refused in the end-of-day summary, with the ones still waiting"""
    discord = FakeDiscord(down=True)
    sender = notifier(discord, log_path)
    sender.send("routine", "refused")
    sender.send("routine", "waiting")
    answers = iter([FakeResponse(400), FakeResponse(503), FakeResponse(200)])
    sender.http_post = lambda url, **kwargs: next(answers)
    sender.retry_failed()

    waiting = sender.report_failed()

    assert waiting == 2

def test_critical_refused_by_the_bot_goes_through_the_webhook(log_path):
    """Post a critical alert through the webhook at once when the bot is refused (a bad token), saving nothing"""
    calls = []

    def bot_refused(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(401 if "/channels/" in url else 200)

    sender = notifier(FakeDiscord(), log_path)
    sender.http_post = bot_refused

    sent = sender.send("critical", "No stop at Alpaca")

    assert (sent, calls[-1], log_path.exists()) == (True, HOOK, False)

def test_saved_critical_is_resent_through_the_webhook_when_the_bot_is_refused(log_path):
    """Resend a saved critical alert through the webhook when the bot is still refused"""
    sender = notifier(FakeDiscord(), log_path)
    sender.failed_log.save("critical", None, ["No stop at Alpaca"], FAILED_AT)
    calls = []

    def bot_refused(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(403 if "/channels/" in url else 200)

    sender.http_post = bot_refused

    resent = sender.retry_failed()

    assert (resent, calls[-1], sender.failed_log.pending()) == (1, HOOK, [])

def by_target(bot_status, hook_status, calls=None):
    """Return a fake post answering bot URLs with bot_status and the webhook with hook_status"""
    def post(url, json=None, headers=None, timeout=None):
        if calls is not None:
            calls.append((url, json["content"]))
        return FakeResponse(bot_status if "/channels/" in url else hook_status)
    return post

def test_critical_is_kept_when_the_bot_is_down_and_the_webhook_refuses(log_path):
    """Keep a saved critical waiting while the bot is down, even if the webhook refuses it (a dead webhook URL)"""
    sender = notifier(FakeDiscord(), log_path)
    sender.failed_log.save("critical", None, ["No stop at Alpaca"], FAILED_AT)
    sender.http_post = by_target(503, 404)

    resent = sender.retry_failed()

    assert (resent, len(sender.failed_log.pending()), sender.failed_log.dropped()) == (0, 1, [])

def test_report_with_no_way_to_post_is_logged_not_saved(log_path, monkeypatch, caplog):
    """Log the summary as a health warning when no channel, token or webhook exists, instead of saving it forever"""
    monkeypatch.delenv("DISCORD_CRITICAL_HOOK", raising=False)
    sender = Notifier(environment="paper", token=None, routes=ROUTES, http_post=FakeDiscord(), sleep=lambda s: None,
                      failed_log=FailedLog(log_path), clock=FakeClock())
    sender.failed_log.save("routine", None, ["one"], FAILED_AT)

    with caplog.at_level(logging.WARNING, logger="health"):
        waiting = sender.report_failed()

    assert (waiting, log_path.exists()) == (1, False)
    assert "couldn't be delivered" in caplog.text

def test_parts_with_no_way_to_post_dont_use_resend_slots(log_path):
    """Skip saved parts whose kind has no channel any more without counting them, so they can't block the rest"""
    sender = notifier(FakeDiscord(), log_path)
    for i in range(NOTIFY_RETRY_BATCH + 2):
        sender.failed_log.save("audit", None, [f"stuck {i}"], FAILED_AT)
    sender.failed_log.save("routine", None, ["good"], FAILED_AT + timedelta(minutes=1))

    resent = sender.retry_failed()

    assert resent == 1

def test_webhook_outage_doesnt_stop_parts_the_bot_can_post(log_path):
    """Keep resending through the bot while only the webhook is down"""
    calls = []
    sender = notifier(FakeDiscord(), log_path, routes={"paper": {"critical": None, "routine": ROUTINE}})
    sender.failed_log.save("critical", None, ["Kill switch on"], FAILED_AT)
    sender.failed_log.save("routine", None, ["Market is open"], FAILED_AT)
    sender.http_post = by_target(200, 503, calls)

    resent = sender.retry_failed()

    assert resent == 1
    assert [entry.kind for entry in sender.failed_log.pending()] == ["critical"]

def test_resend_stops_once_every_way_of_posting_is_down(log_path):
    """Stop the batch after the bot and the webhook have both had an outage"""
    calls = []
    sender = notifier(FakeDiscord(), log_path)
    for i in range(3):
        sender.failed_log.save("critical", None, [f"critical {i}"], FAILED_AT)
    sender.http_post = by_target(503, 503, calls)

    sender.retry_failed()

    assert len(calls) == 2

def test_two_threads_resending_post_each_part_once(log_path):
    """Post each saved part once when the cycle and the heartbeat resend at the same time"""
    calls = []
    sender = notifier(FakeDiscord(), log_path)
    for i in range(5):
        sender.failed_log.save("routine", None, [f"message {i}"], FAILED_AT)

    def slow_post(url, json=None, headers=None, timeout=None):
        calls.append(json["content"])
        time.sleep(0.01)
        return FakeResponse(200)

    sender.http_post = slow_post
    threads = [threading.Thread(target=sender.retry_failed) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 5
