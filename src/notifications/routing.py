"""
routing.py
Check the Discord routing table and find the channel for one kind of message
"""

#Standard Library
from dataclasses import dataclass

ENVIRONMENTS = ("live", "paper", "dev")
BOT_KINDS = ("critical", "audit", "health", "routine")
ASSET_KINDS = ("trades", "shadowing", "summary_trades", "summary_shadow")
ASSETS = ("day", "swing", "options")
ASSET_CLASSES = ("stock", "option")
ANY = "*"

_MISSING = object()

@dataclass(frozen=True)
class Route:
    """Where one message goes: known is False for a kind or asset the table can't route (a bug to fix);
    channel_id is None while that channel isn't set up yet"""
    channel_id: str | None
    known: bool

def _is_channel(value) -> bool:
    """Check a channel entry is None (not set up yet) or an ID string of digits"""
    return value is None or (isinstance(value, str) and value.isdigit())

def _check_assets(environment: str, kind: str, assets) -> tuple[dict | None, list]:
    """Return one per-asset kind's valid {asset: channel} entries and a problem for each bad one"""
    if not isinstance(assets, dict):
        return None, [f"{environment}.{kind}: {assets!r} isn't a table. Expected {{asset: channel ID}}"]
    kept, problems = {}, []
    for asset, channel in assets.items():
        if asset not in ASSETS:
            problems.append(f"{environment}.{kind}: unknown asset {asset!r}. Expected one of {list(ASSETS)}")
        elif not _is_channel(channel):
            problems.append(f"{environment}.{kind}.{asset}: {channel!r} isn't a channel ID. Expected a string of "
                            f"digits or None")
        else:
            kept[asset] = channel
    return kept, problems

def _check_environment(environment: str, table: dict) -> tuple[dict, list]:
    """Return one environment's valid entries and a problem for each bad one"""
    kept, problems = {}, []
    for kind, value in table.items():
        if kind in ASSET_KINDS:
            assets, asset_problems = _check_assets(environment, kind, value)
            problems.extend(asset_problems)
            if assets is not None:
                kept[kind] = assets
        elif kind not in BOT_KINDS and kind != ANY:
            problems.append(f"{environment}: unknown kind {kind!r}. Expected one of "
                            f"{list(BOT_KINDS + ASSET_KINDS + (ANY,))}")
        elif not _is_channel(value):
            problems.append(f"{environment}.{kind}: {value!r} isn't a channel ID. Expected a string of digits or None")
        else:
            kept[kind] = value
    return kept, problems

def check_routes(routes) -> tuple[dict, list]:
    """Return the routing table with every bad entry left out, and a problem line for each one

    Parameters:
        routes (dict): DISCORD_ROUTES, {environment: {kind: channel ID or {asset: channel ID}}}

    Returns:
        (clean routes, list of problem strings); the clean table holds only entries that passed
    """
    if not isinstance(routes, dict):
        return {}, [f"Routing table {routes!r} isn't a table. Expected {{environment: {{kind: channel ID}}}}"]
    clean, problems = {}, []
    for environment, table in routes.items():
        if environment not in ENVIRONMENTS:
            problems.append(f"Unknown environment {environment!r}. Expected one of {list(ENVIRONMENTS)}")
        elif not isinstance(table, dict):
            problems.append(f"{environment}: {table!r} isn't a table. Expected {{kind: channel ID}}")
        else:
            clean[environment], environment_problems = _check_environment(environment, table)
            problems.extend(environment_problems)
    return clean, problems

def feed(holding_type: str | None, asset_class: str = "stock") -> str:
    """Return the routing asset for a message about one position: a stock by its holding type, an option as options

    Parameters:
        holding_type (str | None): The position's holding type, e.g. "day"; not used for an option
        asset_class (str): One of ASSET_CLASSES

    Returns:
        One of ASSETS for a valid holding type (an unknown one is routed to health by send)

    Raises:
        ValueError if asset_class isn't one of ASSET_CLASSES
    """
    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"Unknown asset class {asset_class!r}. Expected one of {list(ASSET_CLASSES)}")
    return "options" if asset_class == "option" else holding_type

def resolve(table: dict | None, kind: str, asset: str | None) -> Route:
    """Return the route for one message in one environment's table

    A bot-wide kind ignores asset. A per-asset kind needs one of ASSETS. A valid kind the table doesn't list goes
    to its "*" entry if there is one.

    Parameters:
        table (dict | None): One environment's checked routes; None before routing is configured
        kind (str): One of BOT_KINDS or ASSET_KINDS
        asset (str | None): One of ASSETS for a per-asset kind

    Returns:
        A Route; known is False for an invalid kind or asset, or one the table doesn't list
    """
    if kind not in BOT_KINDS + ASSET_KINDS or (kind in ASSET_KINDS and asset not in ASSETS):
        return Route(channel_id=None, known=False)
    if table is None:
        return Route(channel_id=None, known=True)
    entry = table.get(kind, _MISSING)
    if kind in ASSET_KINDS and entry is not _MISSING:
        entry = entry.get(asset, _MISSING)
    if entry is _MISSING:
        entry = table.get(ANY, _MISSING)
    if entry is _MISSING:
        return Route(channel_id=None, known=False)
    return Route(channel_id=entry, known=True)
