import math

import numpy as np
import pandas as pd
import pytest

from strategies.supply_demand import SupplyDemand


def model_bars(n=500, half_life=3.0, kappa=0.02, lam=0.005, seed=7):
    """
    Daily bars simulated from the paper's order book model: log price is
    fundamental + lam * cumulative flow + D, with D_t = e^(-rho) * D_(t-1) + kappa * x_t.
    Every 25th bar is a large buy or sell shock.
    """
    rng = np.random.default_rng(seed)
    decay = 0.5 ** (1 / half_life)
    flow = rng.normal(0, 0.3, n)
    shocks = np.arange(25, n, 25)
    flow[shocks] = rng.choice([-1, 1], len(shocks)) * rng.uniform(2, 5, len(shocks))
    displacement = np.zeros(n)
    for t in range(1, n):
        displacement[t] = decay * displacement[t - 1] + kappa * flow[t]
    fundamental = math.log(10) + np.cumsum(rng.normal(0, 0.01, n))
    close = np.exp(fundamental + lam * np.cumsum(flow) + displacement)
    volume = 1e6 * (1 + np.abs(flow)) * rng.uniform(0.8, 1.2, n)
    return pd.DataFrame({"Close": close, "Volume": volume})


def random_walk_bars(seed, n=500):
    rng = np.random.default_rng(seed)
    close = 10 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    return pd.DataFrame({"Close": close, "Volume": rng.lognormal(13, 0.5, n)})


def run(df):
    strategy = SupplyDemand("Supply Demand", df.copy(), "TEST", 10000)
    strategy.generate_signals()
    return strategy.df


def test_fit_matches_brute_force_ols():
    strategy = SupplyDemand("Supply Demand", model_bars(), "TEST", 10000)
    returns = np.diff(np.log(strategy.df["Close"].to_numpy()), prepend=np.nan)
    volatility = pd.Series(returns).rolling(strategy.flow_window).std().shift(1).to_numpy()
    flow = strategy._signed_flow(returns, volatility)
    decayed = strategy._decayed_flow(flow, np.array([0.8]))
    _, slope, t_stat, _ = strategy._fit_resilience(decayed, returns, np.isfinite(flow))

    t = 400
    pairs = np.arange(t - strategy.estimation_window, t)
    ok = np.isfinite(flow[pairs])
    z, y = decayed[0, pairs][ok], returns[pairs + 1][ok]
    fit = np.polyfit(z, y, 1)
    residuals = y - np.polyval(fit, z)
    se = math.sqrt(residuals @ residuals / (len(y) - 2) / ((z - z.mean()) @ (z - z.mean())))
    assert slope[t] == pytest.approx(fit[0])
    assert t_stat[t] == pytest.approx(fit[0] / se)


def test_recovers_resilience_from_model_data():
    last = run(model_bars()).iloc[-1]
    assert 1.5 <= last["half_life"] <= 6
    assert last["kappa"] > 0
    assert last["reversal_t_stat"] <= -SupplyDemand.min_t_stat


def test_round_trips_are_profitable_on_model_data():
    df = run(model_bars())
    close, signal = df["Close"].to_numpy(), df["signal"].to_numpy()
    buys, sells = np.flatnonzero(signal == 1), np.flatnonzero(signal == -1)
    assert len(buys) >= 10
    returns = [close[s] / close[b] - 1 for b, s in zip(buys, sells)]
    assert np.mean(returns) > 0


def test_entries_only_below_steady_state():
    df = run(model_bars())
    entries = df[df["signal"] == 1]
    assert (entries["displacement"] < 0).all()
    assert (entries["steady_state"] > entries["Close"]).all()


def test_signals_alternate_buy_then_sell():
    signal = run(model_bars())["signal"]
    trades = signal[signal != 0].tolist()
    assert trades[0] == 1
    assert all(a != b for a, b in zip(trades, trades[1:]))


def test_no_lookahead():
    full = run(model_bars())
    for k in [150, 300, 450]:
        prefix = run(model_bars().iloc[:k])
        assert (prefix["signal"].to_numpy() == full["signal"].to_numpy()[:k]).all()
        assert np.allclose(prefix["displacement"], full["displacement"].iloc[:k], equal_nan=True)


def test_rarely_trades_random_walks():
    entries = sum((run(random_walk_bars(seed))["signal"] == 1).sum() for seed in range(20))
    model_entries = (run(model_bars())["signal"] == 1).sum()
    assert entries / 20 < model_entries / 10


def test_short_history_stays_flat():
    df = run(model_bars().iloc[:40])
    assert (df["signal"] == 0).all()
    assert df["displacement"].isna().all()
