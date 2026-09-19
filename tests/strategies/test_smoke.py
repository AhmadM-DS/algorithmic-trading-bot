def test_pytest_is_wired_up():
    from strategies.base_strategy import Strategy
    assert Strategy is not None