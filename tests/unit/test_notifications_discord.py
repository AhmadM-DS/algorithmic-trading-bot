"""
test_notifications_discord.py
Unit tests for notifications/discord.py: splitting long messages and posting one part, with a fake Discord
"""

#Third Party Libraries
import pytest
import requests

#Local Imports
from notifications.discord import PostFailure, post_message, split_message

URL = "https://discord.com/api/v10/channels/111111111111111111/messages"

class FakeResponse:
    """Just enough of a requests.Response: a status and a JSON body"""
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

class FakeDiscord:
    """Answer each post with the next queued response (or raise it) and record every call"""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

class FakeSleep:
    """Record sleeps instead of waiting"""
    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)

def post(discord, sleep=None, max_retry_seconds=5):
    """Post one part through the fake Discord with a bot token"""
    return post_message(discord, URL, "hello", headers={"Authorization": "Bot token"}, timeout=5,
                        max_retry_seconds=max_retry_seconds, sleep=sleep or FakeSleep())

def test_short_message_is_one_part():
    """Keep a message under the limit whole"""

    parts = split_message("line one\nline two", limit=2000)

    assert parts == ["line one\nline two"]

def test_long_message_splits_at_line_breaks():
    """Split between lines so no line is cut when lines fit"""
    text = "\n".join(["a" * 6, "b" * 6, "c" * 6])

    parts = split_message(text, limit=13)

    assert parts == ["a" * 6 + "\n" + "b" * 6, "c" * 6]

def test_line_longer_than_limit_is_cut():
    """Cut a single line that alone is over the limit"""

    parts = split_message("x" * 25, limit=10)

    assert parts == ["x" * 10, "x" * 10, "x" * 5]

def test_every_part_fits_and_nothing_is_lost():
    """Keep every part within the limit and every character of the message"""
    text = "\n".join(f"line {i} " + "z" * (i * 7 % 40) for i in range(60))

    parts = split_message(text, limit=100)

    assert all(len(part) <= 100 for part in parts)
    assert "\n".join(parts) == text

def test_blank_lines_inside_a_part_are_kept():
    """Keep blank lines between paragraphs"""

    parts = split_message("first\n\nsecond", limit=2000)

    assert parts == ["first\n\nsecond"]

def test_empty_message_has_no_parts():
    """Return nothing to post for an empty message"""

    parts = split_message("", limit=2000)

    assert parts == []

def test_post_sends_content_headers_and_timeout():
    """Post the part as JSON with the headers, the timeout and only user mentions allowed"""
    discord = FakeDiscord(FakeResponse(200))

    reason = post(discord)

    assert reason is None
    assert discord.calls == [{"url": URL, "json": {"content": "hello", "allowed_mentions": {"parse": ["users"]}},
                              "headers": {"Authorization": "Bot token"}, "timeout": 5}]

def test_post_waits_retry_after_and_retries_once():
    """Wait the seconds Discord asks for after a 429, then post again"""
    discord = FakeDiscord(FakeResponse(429, {"retry_after": 1.5, "global": False}), FakeResponse(200))
    sleep = FakeSleep()

    reason = post(discord, sleep=sleep)

    assert (reason, sleep.slept, len(discord.calls)) == (None, [1.5], 2)

def test_post_gives_up_when_retry_after_is_too_long():
    """Give up at once when Discord asks for a longer wait than the cap, so the cycle never stalls"""
    discord = FakeDiscord(FakeResponse(429, {"retry_after": 64.57, "global": True}))
    sleep = FakeSleep()

    reason = post(discord, sleep=sleep)

    assert (reason.status, sleep.slept, len(discord.calls)) == (429, [], 1)
    assert "64.57" in str(reason)

def test_post_retries_only_once():
    """Give up after a second 429, never loop"""
    discord = FakeDiscord(FakeResponse(429, {"retry_after": 1}), FakeResponse(429, {"retry_after": 1}))

    reason = post(discord)

    assert (reason.status, len(discord.calls)) == (429, 2)

@pytest.mark.parametrize("body", [ValueError("not JSON"), {}, {"retry_after": "soon"}, ["list"],
                                  {"retry_after": float("nan")}, {"retry_after": -1}])
def test_post_gives_up_on_unreadable_retry_after(body):
    """Give up without waiting when the 429's retry_after can't be read or makes no sense"""
    discord = FakeDiscord(FakeResponse(429, body))
    sleep = FakeSleep()

    reason = post(discord, sleep=sleep)

    assert (reason.status, sleep.slept) == (429, [])

@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_post_reports_an_error_status(status):
    """Report a refused or failed post with its status, without retrying"""
    discord = FakeDiscord(FakeResponse(status, {"message": "nope", "code": 50001}))

    reason = post(discord)

    assert (reason.status, len(discord.calls)) == (status, 1)
    assert str(status) in str(reason)

@pytest.mark.parametrize("status, outage", [(503, True), (500, True), (429, True), (None, True), (401, True),
                                            (400, False), (403, False), (404, False)])
def test_outage_is_told_apart_from_a_refused_message(status, outage):
    """Treat network errors (no status), 401 (bad token), 429 and 5xx as an outage, other 4xx as one message refused"""

    assert PostFailure(status, "detail").outage is outage

@pytest.mark.parametrize("error", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_post_reports_a_network_error(error):
    """Report a connection error or timeout instead of raising"""
    discord = FakeDiscord(error)

    reason = post(discord)

    assert reason.status is None
    assert type(error).__name__ in str(reason)
