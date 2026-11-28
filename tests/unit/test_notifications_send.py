"""
test_notifications_send.py
Unit tests for notifications' send: routing, the bot token, the webhook fallback and alert-on-change logging, with a
fake Discord
"""

#Standard Library
import logging

#Third Party Libraries
import pytest
import requests

#Local Imports
import notifications
from config.constants import DISCORD_MENTION
from notifications.routing import check_routes
from notifications.sender import Notifier

CRITICAL = "100000000000000001"
HEALTH = "100000000000000002"
ROUTINE = "100000000000000003"
DAY_TRADES = "100000000000000004"
HOOK = "https://discord.com/api/webhooks/1/fake"

ROUTES = {"paper": {"critical": CRITICAL, "health": HEALTH, "routine": ROUTINE, "audit": None,
                    "trades": {"day": DAY_TRADES, "options": None}}}

class FakeResponse:
    """Just enough of a requests.Response: a status and a JSON body"""
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.body = body

    def json(self):
        return self.body

class FakeDiscord:
    """Answer every post with the next queued answer (200 when none is queued) and record each call"""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "content": json["content"], "headers": headers})
        answer = self.answers.pop(0) if self.answers else FakeResponse()
        if isinstance(answer, Exception):
            raise answer
        return answer

    def channels(self):
        return [call["url"].split("/channels/")[1].split("/")[0] if "/channels/" in call["url"] else "webhook"
                for call in self.calls]

def notifier(discord, token="bot-token", routes=ROUTES, environment="paper"):
    """Build a Notifier on the fake Discord that never sleeps"""
    return Notifier(environment=environment, token=token, routes=routes, http_post=discord,
                    sleep=lambda seconds: None, hook_url=HOOK)

def test_message_goes_to_its_kinds_channel_with_the_bot_token():
    """Post a routine message to the routine channel, authorized as the bot"""
    discord = FakeDiscord()

    sent = notifier(discord).send("routine", "Market is open")

    assert sent is True
    assert discord.calls == [{"url": f"https://discord.com/api/v10/channels/{ROUTINE}/messages",
                              "content": "Market is open", "headers": {"Authorization": "Bot bot-token"}}]

def test_asset_message_goes_to_that_assets_channel():
    """Post a day trade to the day trades channel"""
    discord = FakeDiscord()

    notifier(discord).send("trades", "Bought AAPL", asset="day")

    assert discord.channels() == [DAY_TRADES]

def test_critical_mentions_the_owner_once():
    """Add the owner's mention to a critical message, never twice"""
    discord = FakeDiscord()
    sender = notifier(discord)

    sender.send("critical", "Kill switch on")
    sender.send("critical", f"Bot crashed {DISCORD_MENTION}")

    assert [call["content"] for call in discord.calls] == [f"Kill switch on {DISCORD_MENTION}",
                                                           f"Bot crashed {DISCORD_MENTION}"]

def test_other_kinds_get_no_mention():
    """Leave the mention off anything that isn't critical"""
    discord = FakeDiscord()

    notifier(discord).send("health", "Cycle overran")

    assert DISCORD_MENTION not in discord.calls[0]["content"]

def test_secret_in_a_message_is_redacted(monkeypatch):
    """Mask a secret's value before it leaves the bot"""
    monkeypatch.setenv("DB_PASSWORD", "hunter2-secret")
    discord = FakeDiscord()

    notifier(discord).send("routine", "login failed with hunter2-secret")

    assert discord.calls[0]["content"] == "login failed with ********"

def test_long_message_is_posted_in_parts():
    """Post a message over Discord's limit as several parts, in order"""
    discord = FakeDiscord()
    text = "\n".join(["x" * 1500, "y" * 1500])

    sent = notifier(discord).send("routine", text)

    assert sent is True
    assert [call["content"] for call in discord.calls] == ["x" * 1500, "y" * 1500]

def test_failed_part_stops_the_rest():
    """Stop posting a message's remaining parts once one part fails"""
    discord = FakeDiscord(FakeResponse(), FakeResponse(503))
    text = "\n".join(["x" * 1500, "y" * 1500, "z" * 1500])

    sent = notifier(discord).send("routine", text)

    assert sent is False
    assert len(discord.calls) == 2

def test_without_token_critical_uses_the_webhook():
    """Send critical through today's webhook while the bot token isn't set up"""
    discord = FakeDiscord()

    sent = notifier(discord, token=None).send("critical", "Kill switch on")

    assert sent is True
    assert discord.calls == [{"url": HOOK, "content": f"Kill switch on {DISCORD_MENTION}", "headers": None}]

def test_without_token_other_kinds_are_only_logged(caplog):
    """Log a non-critical message instead of posting while the bot token isn't set up"""
    discord = FakeDiscord()

    with caplog.at_level(logging.INFO, logger="routine"):
        sent = notifier(discord, token=None).send("routine", "Market is open")

    assert (sent, discord.calls) == (False, [])
    assert "Market is open" in caplog.text

def test_kind_without_channel_yet_is_only_logged():
    """Log a listed kind whose channel isn't filled in yet, without a "no route" warning"""
    discord = FakeDiscord()

    sent = notifier(discord).send("audit", "Audit passed")

    assert (sent, discord.calls) == (False, [])

def test_critical_without_channel_yet_uses_the_webhook():
    """Send critical through the webhook when the environment's critical channel isn't filled in yet"""
    discord = FakeDiscord()
    routes = {"paper": {"critical": None, "*": ROUTINE}}

    notifier(discord, routes=routes).send("critical", "Kill switch on")

    assert discord.channels() == ["webhook"]

def test_without_hook_or_token_critical_is_only_logged(monkeypatch, caplog):
    """Log a critical message when neither the bot nor the webhook is set up, without raising"""
    monkeypatch.delenv("DISCORD_CRITICAL_HOOK", raising=False)
    discord = FakeDiscord()
    sender = Notifier(environment="paper", token=None, routes=ROUTES, http_post=discord, sleep=lambda s: None)

    with caplog.at_level(logging.INFO):
        sent = sender.send("critical", "Kill switch on")

    assert (sent, discord.calls) == (False, [])
    assert "Kill switch on" in caplog.text

def test_unknown_kind_goes_to_health_with_a_prefix():
    """Send a misspelled kind to the health channel, marked so the bug is seen"""
    discord = FakeDiscord()

    notifier(discord).send("critcal", "Kill switch on")

    assert discord.channels() == [HEALTH]
    assert discord.calls[0]["content"] == "[no route: critcal/None] Kill switch on"

def test_unknown_route_is_logged_once(caplog):
    """Warn once per missing route, not on every message"""
    discord = FakeDiscord()
    sender = notifier(discord)

    with caplog.at_level(logging.WARNING, logger="health"):
        sender.send("trades", "Bought SPY", asset="swing")
        sender.send("trades", "Sold SPY", asset="swing")

    assert caplog.text.count("No Discord route") == 1
    assert discord.channels() == [HEALTH, HEALTH]

def test_discord_down_and_back_are_logged_once_each(caplog):
    """Log one line when posting starts failing and one when it works again"""
    discord = FakeDiscord(FakeResponse(503), FakeResponse(503), FakeResponse(200))
    sender = notifier(discord)

    with caplog.at_level(logging.INFO, logger="health"):
        results = [sender.send("routine", "one"), sender.send("routine", "two"), sender.send("routine", "three")]

    assert results == [False, False, True]
    assert caplog.text.count("Discord posting failed") == 1
    assert caplog.text.count("Discord posting works again") == 1

def test_webhook_success_doesnt_clear_a_bot_outage(caplog):
    """Keep the bot's outage open when only the webhook works, so the log never flips down / back / down"""
    discord = FakeDiscord(FakeResponse(401), FakeResponse(200), FakeResponse(401))
    sender = notifier(discord, routes={"paper": {"critical": None, "routine": ROUTINE}})

    with caplog.at_level(logging.INFO, logger="health"):
        sender.send("routine", "one")
        sender.send("critical", "two")
        sender.send("routine", "three")

    assert discord.channels() == [ROUTINE, "webhook", ROUTINE]
    assert caplog.text.count("Discord posting failed") == 1
    assert "posting works again" not in caplog.text

@pytest.mark.parametrize("error", [requests.ConnectionError("down"), RuntimeError("bug")])
def test_send_never_raises(error):
    """Return False instead of raising, even on an unexpected error"""
    discord = FakeDiscord(error)

    sent = notifier(discord).send("routine", "Market is open")

    assert sent is False

def test_empty_message_is_not_posted():
    """Post nothing for an empty message"""
    discord = FakeDiscord()

    sent = notifier(discord).send("routine", "")

    assert (sent, discord.calls) == (False, [])

def test_wrappers_map_to_kinds(monkeypatch):
    """Keep the old helpers for old modules: critical to critical, routine and trades both to routine"""
    discord = FakeDiscord()
    monkeypatch.setattr(notifications, "_notifier", notifier(discord))

    notifications.send_critical("a")
    notifications.send_routine("b")
    notifications.send_trades("c")

    assert discord.channels() == [CRITICAL, ROUTINE, ROUTINE]

def test_configure_routes_later_sends(monkeypatch, tmp_path):
    """Use the configured environment, token and routes for every send after configure"""
    monkeypatch.setattr(notifications, "_notifier", notifications._notifier)
    discord = FakeDiscord()

    problems = notifications.configure("paper", "bot-token", ROUTES, process="bot", log_dir=tmp_path,
                                       http_post=discord, sleep=lambda s: None)
    notifications.send("health", "Cycle overran")

    assert problems == []
    assert discord.channels() == [HEALTH]

def test_configure_reports_and_alerts_bad_entries(monkeypatch, tmp_path):
    """Return each skipped entry and send one critical alert listing them, routing the rest"""
    monkeypatch.setattr(notifications, "_notifier", notifications._notifier)
    discord = FakeDiscord()
    routes = {"paper": {"critical": CRITICAL, "health": "#health", "routine": ROUTINE}}

    problems = notifications.configure("paper", "bot-token", routes, process="bot", log_dir=tmp_path,
                                       http_post=discord, sleep=lambda s: None)

    assert len(problems) == 1
    assert discord.channels() == [CRITICAL]
    assert "health" in discord.calls[0]["content"]

def test_configure_reports_an_environment_without_routes(monkeypatch, tmp_path):
    """Report an environment the table has no routes for, and still send critical through the webhook"""
    monkeypatch.setattr(notifications, "_notifier", notifications._notifier)
    monkeypatch.setenv("DISCORD_CRITICAL_HOOK", HOOK)
    discord = FakeDiscord()

    problems = notifications.configure("staging", "bot-token", ROUTES, process="bot", log_dir=tmp_path,
                                       http_post=discord, sleep=lambda s: None)

    assert len(problems) == 1
    assert discord.channels() == ["webhook"]

@pytest.mark.parametrize("routes", [{"paper": {"health": HEALTH}}, {"paper": {"critical": 1234, "health": HEALTH}}])
def test_critical_without_a_usable_route_goes_through_the_webhook(routes):
    """Never reroute critical to health: with its route missing or mistyped it goes through the webhook"""
    discord = FakeDiscord()
    clean, _ = check_routes(routes)

    notifier(discord, routes=clean).send("critical", "Kill switch on")

    assert discord.channels() == ["webhook"]
    assert "[no route" not in discord.calls[0]["content"]

def test_critical_with_nowhere_to_go_is_a_warning(monkeypatch, caplog):
    """Log a critical alert that can't be posted anywhere as a health warning with its text"""
    monkeypatch.delenv("DISCORD_CRITICAL_HOOK", raising=False)
    sender = Notifier(environment="paper", token=None, routes=ROUTES, http_post=FakeDiscord(), sleep=lambda s: None)

    with caplog.at_level(logging.WARNING, logger="health"):
        sender.send("critical", "Kill switch on")

    assert "Kill switch on" in caplog.text

def test_refused_message_doesnt_change_the_outage_state(caplog):
    """Log no "posting failed" for one refused message (400); only an outage changes the state"""
    discord = FakeDiscord(FakeResponse(400), FakeResponse(200))
    sender = notifier(discord)

    with caplog.at_level(logging.INFO, logger="health"):
        sender.send("routine", "bad one")
        sender.send("routine", "good one")

    assert "Discord posting failed" not in caplog.text
    assert "posting works again" not in caplog.text
