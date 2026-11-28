"""
test_notifications_routing.py
Unit tests for notifications/routing.py: checking the routing table and finding a message's channel
"""

#Third Party Libraries
import pytest

#Local Imports
from config.constants import DISCORD_ROUTES
from notifications.routing import (ASSET_KINDS, ASSETS, BOT_KINDS, ENVIRONMENTS, Route, check_routes, feed,
                                   resolve)

CHANNEL = "111111111111111111"
OTHER = "222222222222222222"

def test_every_kind_has_a_route_in_every_environment():
    """Give every kind and asset a known route in each environment of DISCORD_ROUTES"""
    clean, problems = check_routes(DISCORD_ROUTES)

    unrouted = [(environment, kind, asset) for environment in ENVIRONMENTS
                for kind in BOT_KINDS + ASSET_KINDS
                for asset in ((None,) if kind in BOT_KINDS else ASSETS)
                if not resolve(clean.get(environment), kind, asset).known]

    assert (problems, unrouted) == ([], [])

def test_bot_kind_finds_its_channel():
    """Return the channel set for a bot-wide kind"""

    route = resolve({"health": CHANNEL}, "health", None)

    assert route == Route(channel_id=CHANNEL, known=True)

def test_asset_kind_finds_its_assets_channel():
    """Return the channel set for one asset of a per-asset kind"""
    table = {"trades": {"day": CHANNEL, "options": OTHER}}

    route = resolve(table, "trades", "options")

    assert route == Route(channel_id=OTHER, known=True)

def test_bot_kind_ignores_an_asset():
    """Route a bot-wide kind the same with or without an asset"""

    route = resolve({"critical": CHANNEL}, "critical", "day")

    assert route == Route(channel_id=CHANNEL, known=True)

def test_any_entry_catches_kinds_not_listed():
    """Send every kind the table doesn't list to its "*" channel (dev-all)"""
    table = {"critical": CHANNEL, "*": OTHER}

    routes = [resolve(table, "routine", None), resolve(table, "trades", "swing")]

    assert routes == [Route(channel_id=OTHER, known=True)] * 2

def test_channel_not_set_up_yet_is_known_without_channel():
    """Treat a listed kind whose channel ID isn't filled in yet as known, with no channel"""

    route = resolve({"routine": None}, "routine", None)

    assert route == Route(channel_id=None, known=True)

def test_no_table_means_nothing_set_up_yet():
    """Treat every valid kind as known with no channel before routing is configured"""

    route = resolve(None, "audit", None)

    assert route == Route(channel_id=None, known=True)

@pytest.mark.parametrize("kind, asset", [("critcal", None), ("trades", None), ("trades", "futures")])
def test_unknown_kind_or_asset_is_unknown(kind, asset):
    """Mark a misspelled kind, a per-asset kind without an asset, or an unknown asset as unknown, even unconfigured"""

    routes = [resolve(None, kind, asset), resolve({"*": CHANNEL}, kind, asset)]

    assert routes == [Route(channel_id=None, known=False)] * 2

def test_valid_kind_missing_from_table_is_unknown():
    """Mark a valid kind the environment's table doesn't list (and has no "*") as unknown"""

    route = resolve({"critical": CHANNEL}, "audit", None)

    assert route == Route(channel_id=None, known=False)

def test_check_routes_keeps_good_entries():
    """Keep a valid table unchanged with no problems"""
    routes = {"live": {"critical": CHANNEL, "trades": {"day": OTHER, "swing": None}}, "dev": {"*": None}}

    clean, problems = check_routes(routes)

    assert (clean, problems) == (routes, [])

@pytest.mark.parametrize("routes, kept", [
    ({"staging": {"critical": CHANNEL}, "live": {"critical": CHANNEL}}, {"live": {"critical": CHANNEL}}),
    ({"live": "not a table"}, {}),
    ({"live": {"critcal": CHANNEL, "health": CHANNEL}}, {"live": {"health": CHANNEL}}),
    ({"live": {"critical": "#live-critical"}}, {"live": {}}),
    ({"live": {"critical": 111111111111111111}}, {"live": {}}),
    ({"live": {"trades": CHANNEL}}, {"live": {}}),
    ({"live": {"trades": {"day": CHANNEL, "futures": CHANNEL}}}, {"live": {"trades": {"day": CHANNEL}}}),
    ({"live": {"trades": {"day": ""}}}, {"live": {"trades": {}}}),
])
def test_check_routes_skips_each_bad_entry_and_keeps_the_rest(routes, kept):
    """Skip an unknown environment, kind or asset, a channel that isn't an ID string, and a per-asset kind without
    its asset table; keep everything else"""

    clean, problems = check_routes(routes)

    assert clean == kept
    assert len(problems) == 1

def test_check_routes_refuses_a_table_that_isnt_a_dict():
    """Return no routes and one problem when the whole setting is the wrong type"""

    clean, problems = check_routes(["live"])

    assert (clean, len(problems)) == ({}, 1)

@pytest.mark.parametrize("holding_type, asset_class, expected", [("day", "stock", "day"), ("swing", "stock", "swing"),
                                                                 ("day", "option", "options"),
                                                                 (None, "option", "options")])
def test_feed_picks_the_routing_asset_from_holding_type_and_asset_class(holding_type, asset_class, expected):
    """Route stocks by holding type and options by asset class, from one place"""

    assert feed(holding_type, asset_class) == expected

def test_feed_refuses_an_unknown_asset_class():
    """Refuse an asset class routing doesn't know, naming the ones it does"""
    with pytest.raises(ValueError, match="futures"):
        feed("day", "futures")
