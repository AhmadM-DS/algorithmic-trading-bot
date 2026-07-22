# Machine learning / reinforcement learning future

Running notes on adding a learned signal source alongside the rule-based
strategies (`MACDStrategy`, `RSIStrategy`, `MovingAverageStrategy`,
`Momentum`, `ICT`).

---

## Goal

Add an `RLStrategy` that plugs into the existing
`Strategy` interface (`src/strategies/base_strategy.py`) the same way every
other strategy does — it needs to implement `generate_signals()` and produce
a `signal` column of `1` (buy) / `-1` (sell) / `0` (hold) on `self.df`, so
`main.py`'s `evaluate_and_trade()`, `risk.py`'s `DailyRiskState`, and
`base_strategy.backtest()` all keep working without changes. The model
should be a new *signal source*, not a replacement for the risk/execution
pipeline that already exists.

- [ ] Decide the class boundary: does `RLStrategy` wrap a trained policy and
      call it inside `generate_signals()`, or does training/inference live
      in a separate module (e.g. `src/ml/`) that `RLStrategy` just calls
      into? Leaning toward the latter — keeps `strategies/` free of
      training code and matches how `indicators/` and `patterns/` are
      already split out from strategy logic.

---

## Why reinforcement learning (vs. supervised)

The rule-based strategies all answer "is this pattern present right now?".
An RL approach instead lets the model learn *when to act* by directly
optimizing for reward (P&L, risk-adjusted return) rather than predicting a
proxy label (e.g. "will price be up in N bars?"). That fits this bot's
existing shape better than supervised learning:

- The bot already has a natural episode structure — one trading day per
  ticker, bounded by market open/close (`src/market_hours.py`).
- Reward is well defined: realized P&L per trade, same quantity
  `risk.py`/`trader.py` already compute.
- Action space maps directly onto the existing signal convention:
  `{buy, sell, hold}` == `{1, -1, 0}`.

Supervised learning isn't off the table (e.g. a classifier that scores
`Momentum`/`ICT` pattern quality — see "Model-assisted pattern
confirmation" below) but the primary long-term goal is a policy trained
with RL.

---

## Environment design

- [ ] Define the **state/observation**: likely a window of recent bars plus
      derived indicators already available via `src/indicators/` (RSI,
      MACD, EMA, VWAP) rather than raw OHLCV, so the model isn't relearning
      indicator math from scratch. Needs to be decided per-timeframe once
      the regime filter work (see `feature_ideas.md` — "Regime filter /
      multi-timeframe direction vs timing") lands, since direction/timing
      separation is likely relevant state for the model too.
- [ ] Define the **action space**: start with discrete `{buy, sell, hold}`
      to match the existing signal convention. Position sizing stays with
      `trader.size_position()` — the model decides direction/timing, not
      size, at least initially.
- [ ] Define the **reward function**: realized P&L per closed trade is the
      obvious start (mirrors `base_strategy.backtest()`'s profit
      calculation), but raw P&L rewards excessive risk-taking. Consider
      reward shaping (e.g. Sharpe-like penalty for drawdown, or the same
      `profit_target`/`loss_limit` bounds `risk.py` already enforces) so
      the learned policy doesn't just relearn bigger-is-better.
- [ ] Define the **episode boundary**: one ticker-day seems natural given
      `market_time_slots()`, but multi-day episodes may be needed if we
      want the model to learn to hold past a single session.
- [ ] Decide whether training uses `data/cleaned/*.csv` history directly
      (via `cleaner.py`/`load_ticker_data()`) or needs a dedicated
      backtesting environment (e.g. a `gymnasium.Env` wrapper) separate
      from `Strategy.backtest()`, since the latter assumes a rule-based
      signal is already computed rather than an agent acting step-by-step.

---

## Framework / library choices

- [ ] Pick an RL library. Candidates: `stable-baselines3` (simplest to get
      a PPO/DQN agent running against a custom `gymnasium.Env`),
      `Ray RLlib` (more scalable, more setup). Leaning toward
      `stable-baselines3` to start given the project's current size and
      the fact `requirements.txt` doesn't have any ML dependencies yet.
- [ ] `gymnasium` (maintained fork of OpenAI Gym) for the environment
      interface if going the `stable-baselines3` route.
- [ ] Decide whether model training/inference needs `numpy`/`torch`
      pinned versions compatible with the rest of `requirements.txt`
      (currently pandas 3.x, Python 3.14 per the venv) — worth checking
      ecosystem support for Python 3.14 before committing, since RL/ML
      libraries often lag new Python releases.

---

## Training data and backtesting parity

Source: related to `feature_ideas.md` — "Backtest sizing doesn't match live
sizing" — the same live/backtest parity problem applies here, arguably more
so for a learned policy than a rule-based one.

- [ ] Training needs a large enough universe of historical ticker-days to
      generalize beyond the current `MAX_TICKERS = 20`/day screener output
      (`src/main.py`). Decide whether to train only on tickers the screener
      would have selected historically (`DEFAULT_FILTERS` in
      `src/config.py`), or on a broader universe, then filter at inference
      time the same way live trading does.
  - [ ] TradingView's scanner (`src/screener.py`) is live-only — there's no
        historical screener replay yet, so backtesting/training against
        "what the screener would have shown on day X" isn't possible
        without building that first.
- [ ] Avoid lookahead bias: any indicator/feature computed for a given bar
      must only use data available up to that bar. Worth a specific check
      once real feature engineering starts, since `technical_indicators.py`
      currently has both a vectorized `calculate(df)` (batch, backtest-style)
      and an incremental `update(new_candle)` (live-style) — training should
      probably exercise the incremental path so the model sees the same
      view of the world it'll get live.

---

## Model-assisted pattern confirmation (near-term, non-RL)

A lower-lift stepping stone before full RL: a supervised classifier that
scores confidence on top of the existing pattern detectors in
`src/patterns/candlestick_patterns.py` (Bull Flag, Flat Top, Liquidity
Sweep, Market Structure Shift, Fair Value Gap) rather than acting on its
own. `Momentum` and `ICT` already gate entries on these patterns firing —
a model could rank/filter pattern hits instead of trading them all
equally, without touching the signal interface.

- [ ] Decide if this is worth building as a stepping stone (faster to
      ship, easier to validate against known good/bad trade outcomes
      logged in `Trades`/`Metrics` tables) or if it's a distraction from
      the RL goal.

---

## Evaluation before going live

- [ ] Any trained policy needs to run in `Trade_Type = 'Backtest'` mode
      (same convention as `base_strategy.backtest()`) against out-of-sample
      data before ever touching `Trade_Type = 'Live'`.
- [ ] Given `risk.py`'s existing halting logic (profit target / loss limit
      per strategy), decide whether an RL strategy should be subject to the
      exact same `DailyRiskState` guardrails as the rule-based strategies,
      or needs tighter bounds initially (e.g. lower `risk_fraction`,
      stricter `loss_limit`) while it's unproven.
- [ ] Paper-trade the policy for a meaningful sample size before
      considering it alongside the other five strategies in
      `main.py`'s `strategies` list.

---
