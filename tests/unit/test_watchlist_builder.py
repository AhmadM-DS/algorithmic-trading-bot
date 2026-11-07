from watchlist.builder import combine

def test_screener_first_then_popular():
    assert combine(["KTTA", "SOBR"], ["GME", "AMC"], set(), 20) == ["KTTA", "SOBR", "GME", "AMC"]

def test_no_repeats():
    assert combine(["GME"], ["GME", "AMC"], set(), 20) == ["GME", "AMC"]

def test_inactive_left_out_everywhere():
    assert combine(["DEAD", "KTTA"], ["DEAD2", "GME"], {"DEAD", "DEAD2"}, 20) == ["KTTA", "GME"]

def test_cap_keeps_screener_hits():
    assert combine(["A", "B"], ["C", "D", "E"], set(), 3) == ["A", "B", "C"]

def test_nothing_screened():
    assert combine([], ["GME"], set(), 20) == ["GME"]

def test_untradable_screener_hit_gives_its_slot_to_a_popular_ticker():
    """Leave out a hit Alpaca can't trade and fill the cap from the popular list instead"""
    assert combine(["ZZZQ", "KTTA"], ["GME", "AMC"], {"ZZZQ"}, 2) == ["KTTA", "GME"]
