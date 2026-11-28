"""
test_alpaca_client.py
Unit tests for alpaca_client.py's api_usage front door
"""

#Third Party Libraries
import pytest

#Local Imports
from alpaca_client import api_usage, create_alpaca_shd_client, create_alpaca_trading_client
from execution.rate_limiter import ApiUsage

@pytest.mark.parametrize("build", [lambda: create_alpaca_trading_client("key", "secret"),
                                   lambda: create_alpaca_shd_client("key", "secret")])
def test_api_usage_reads_new_client_as_unused(build):
    """Report no calls and no remaining count for a client that hasn't called Alpaca"""
    client = build()

    usage = api_usage(client)

    assert usage == ApiUsage(calls_in_window=0, last_remaining=None, total_calls=0)

def test_api_usage_counts_calls_through_client_limiter():
    """Count a call made through the client's own limiter"""
    client = create_alpaca_trading_client("key", "secret")
    client._session.limiter.wait()

    usage = api_usage(client)

    assert usage.calls_in_window == 1
    assert usage.total_calls == 1

def test_api_usage_refuses_client_without_limiter():
    """Raise for a client that wasn't built through alpaca_client, since its calls aren't counted"""
    class BareClient:
        _session = object()

    with pytest.raises(TypeError, match="rate limiter"):
        api_usage(BareClient())
