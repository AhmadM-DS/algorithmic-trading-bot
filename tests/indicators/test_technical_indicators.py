import pytest
import pandas as pd
from indicators.technical_indicators import RSI, EMA, MACD, VWAP

def make_fixture_df():
    return pd.DataFrame({
        "close":  [12, 31, 41,  4,   1,  5, 32, 53, 62, 13, 53, 12, 53, 21, 42, 12, 52],
        "high":   [13, 32, 42,  5,   2,  6, 33, 54, 63, 14, 54, 13, 54, 22, 43, 13, 53],
        "low":    [11, 30, 40,  3, 0.5,  4, 31, 52, 61, 12, 52, 11, 52, 20, 41, 11, 51],
        "volume": [1120, 1310, 1410, 1040, 1010, 1050, 1320, 1530, 1620,
                   1130, 1530, 1120, 1530, 1210, 1420, 1120, 1520]
    })

def test_rsi_calculate_and_update_agree():
    df = make_fixture_df()
    rsi = RSI(period=14)
    batch_result = rsi.calculate(df)
    streaming_rsi = RSI(period=14)
    updated_rsi = []

    for _, row in df.iterrows():
        update_rsi = streaming_rsi.update(row)
        updated_rsi.append(update_rsi)
    assert batch_result.iloc[-1] == pytest.approx(updated_rsi[-1])

def test_ema_calculate_and_update_agree():
    df = make_fixture_df()
    ema = EMA(period=9)
    batch_result = ema.calculate(df)
    streaming_ema = EMA(period=9)
    updated_emas = []
    for _, row in df.iterrows():
        update_ema = streaming_ema.update(row)
        updated_emas.append(update_ema)
    assert batch_result.iloc[-1] == pytest.approx(updated_emas[-1])

def test_macd_calculate_and_update_agree():
    df = make_fixture_df()
    macd = MACD(short_period=12, long_period=26, signal_period=9)
    batch_result = macd.calculate(df)
    streaming_macd = MACD(short_period=12, long_period=26, signal_period=9)
    for _, row in df.iterrows():
        latest_macd = streaming_macd.update(row)
    assert batch_result["macd_line"].iloc[-1] == pytest.approx(latest_macd["macd_line"])
    assert batch_result["signal_line"].iloc[-1] == pytest.approx(latest_macd["signal_line"])
    assert batch_result["histogram"].iloc[-1] == pytest.approx(latest_macd["histogram"])

def test_VWAP_calculate_and_update_agree():
    df = make_fixture_df()
    vwap = VWAP()
    batch_result = vwap.calculate(df)
    streaming_vwap = VWAP()
    for _, row in df.iterrows():
        latest_vwap = streaming_vwap.update(row)
    assert batch_result.iloc[-1] == pytest.approx(latest_vwap)