# Backtesting future

Running notes on making backtesting a first-class, trustworthy part of this
project instead of something we eyeball in a notebook. Not a spec — just
enough context so we can pick this thread back up without re-deriving it.
Add a new `##` section per sub-topic; check items off or delete them once
they land.

---

## Where things stand today

- `Strategy.backtest()` in
  [src/strategies/base_strategy.py](../src/strategies/base_strategy.py)
  simulates trades bar-by-bar off `generate_signals()` output, hardcodes
  `quantity=1` per trade (see `feature_ideas.md` — "Backtest sizing doesn't
  match live sizing"), and writes results straight into the `Trades` and
  `Metrics` tables (`Trade_Type = 'Backtest'`) via `src/db.py`.
- Exploration happens ad hoc in
  [notebooks/initial_backtesting.ipynb](../notebooks/initial_backtesting.ipynb) —
  useful for one-off checks but nothing there is repeatable or asserted
  against.
- There is currently **no automated test suite** anywhere in the repo (no
  `tests/` directory, no `pytest` in `requirements.txt`). Every strategy,
  indicator, and pattern detector is validated by eyeballing backtest
  output or notebook plots.
- Backtest results are only visible via direct DB queries or the notebook —
  the website (`website/frontend/dashboard.html`) currently graphs *live*
  trade P&L (`website/backend/routers/dashboard.py`), not backtest runs.

---

## pytest test suite

Goal: catch regressions in signal logic, indicators, and pattern detectors
before they reach a live/paper account, and give the backtest itself
something to be validated against.

- [ ] Add `pytest` (and `pytest-cov`) to `requirements.txt`, create a
      `tests/` directory mirroring `src/` (`tests/strategies/`,
      `tests/indicators/`, `tests/patterns/`, etc.), and a `pytest.ini` /
      `pyproject.toml` `[tool.pytest.ini_options]` block that points
      `rootdir`/`pythonpath` at `src/` (strategy modules currently import
      each other with bare names like `from strategies.base_strategy import
      Strategy`, so tests need the same import root main.py gets today).
- [ ] **Indicators** (`src/indicators/technical_indicators.py`): the
      easiest correctness win — `RSI`, `EMA`, `MACD`, `VWAP` each expose
      both a vectorized `calculate(df)` and incremental `update(new_candle)`
      path. Write tests that feed the same fixture series through both
      paths and assert they agree (this is exactly the kind of drift that's
      easy to introduce silently), plus known-value tests against a
      hand-computed or reference (e.g. TA-Lib/pandas-ta) result.
- [ ] **Pattern detectors**
      (`src/patterns/candlestick_patterns.py`): construct small synthetic
      OHLCV fixtures that clearly do/don't contain each pattern (Bull Flag,
      Flat Top, Liquidity Sweep, Market Structure Shift, Fair Value Gap)
      and assert detection fires/doesn't fire. Cheap to write, and this is
      the layer `Momentum` and `ICT` both depend on for entries.
- [ ] **Strategies** (`src/strategies/*.py`): given a fixed synthetic price
      series, assert `generate_signals()` produces the expected
      buy/sell/hold sequence. Mock or fixture `get_connection()`
      (`src/db.py`) so strategy tests don't need a live Azure SQL
      connection — `backtest()` currently writes directly to the DB inside
      the method, which makes it untestable without either a real DB or a
      connection fixture/mock.
- [ ] **Risk state** (`src/risk.py`): `DailyRiskState` has clear,
      already-documented invariants (one round-trip per ticker/strategy/day,
      profit-target/loss-limit halting) that are straightforward to unit
      test without any DB or network dependency — good first target since
      it's pure logic.
- [ ] Decide on a coverage bar (or skip enforcing one) once the suite
      exists — don't block on 100%, but flag strategy/risk logic
      specifically as code that shouldn't regress silently.

---

## Backtest engine improvements

- [ ] Fix the sizing gap noted in `feature_ideas.md`
      ("Backtest sizing doesn't match live sizing") — `backtest()` should
      call the same sizing formula `trader.size_position()` uses live, once
      there's a capital-based (non-Alpaca-account) variant.
- [ ] Separate "run a backtest and get metrics back" from "run a backtest
      and write to the DB" — right now `Strategy.backtest()` does both in
      one method, which is part of why it's hard to unit test. A pure
      function that takes a DataFrame + signals and returns metrics (win
      rate, risk/reward, % return) would be testable in isolation; the DB
      write can wrap it.
- [ ] Once a screener-replay exists (see `machine_learning_future.md` —
      training data needs "what the screener would have shown on day X"),
      backtests could run against the *historical* screener output instead
      of only tickers picked today, which would make multi-strategy,
      multi-ticker backtest runs actually representative of what the live
      bot would have selected.

---

## More EDA

`notebooks/initial_backtesting.ipynb` is the only exploratory work right
now. Ideas for expanding it, or splitting it into more focused notebooks:

- [ ] Per-strategy win-rate/return distribution across the ticker universe
      (not just single-ticker spot checks) — right now it's easy to judge a
      strategy off one or two lucky/unlucky tickers.
- [ ] Correlation between screener filter values
      (`DEFAULT_FILTERS` in `src/config.py` — price range, % change,
      relative volume, float size) and strategy outcomes, to sanity check
      whether the screener is actually surfacing tickers each strategy does
      well on.
- [ ] Trade-duration and time-of-day analysis — `Momentum` restricts
      entries to specific windows (`is_within_window` in
      `src/market_hours.py`); worth visualizing whether wins cluster in
      that window or whether the window needs adjusting.
- [ ] Drawdown and risk/reward distributions per strategy over the
      `Metrics` table history, not just the aggregate figures
      `website/backend/routers/dashboard.py` already computes for live
      trades (Sharpe, max drawdown, profit factor) — reuse that math
      against backtest data instead of live.
- [ ] Once `RLStrategy` exists (`machine_learning_future.md`), EDA on
      state/feature distributions the model would see is a prerequisite
      before training — same fixture data this section is already asking
      for.

---

## Backtesting page on the website

The dashboard site (`website/frontend/`) already has a sidenav pattern
(Account Overview → `index.html`, Dashboard → `dashboard.html`, Trade Logs →
`tradelogs.html`, Expenses → `expenses.html`), each backed by a FastAPI
router under `website/backend/routers/` and its own JS/CSS pair. A
Backtesting page would follow the same shape.

- [ ] New router `website/backend/routers/backtest.py` exposing
      backtest-specific endpoints — likely `Trade_Type = 'Backtest'` filtered
      versions of what `dashboard.py`/`overview.py` already compute
      (equity curve, win/loss, Sharpe, max drawdown, profit factor), plus
      per-strategy/per-ticker breakdowns since backtests span more tickers
      than live trading's `MAX_TICKERS = 20`.
- [ ] New page `website/frontend/backtest.html` +
      `js/backtest.js` + `css/backtest.css`, added to the sidenav in every
      existing page (`index.html`, `dashboard.html`, `tradelogs.html`,
      `expenses.html` — the nav is duplicated per page today, not a shared
      partial, so a new link needs adding in all four).
- [ ] Decide the page's core view: probably strategy-vs-strategy comparison
      (return, win rate, risk/reward side by side) since that's the
      question backtests exist to answer, plus a way to filter by
      ticker/date range the way `dashboard.py`'s `/api/dashboard` already
      supports (`strategy`/`symbol` query params).
- [ ] Once the backtest engine changes above land (esp. sizing parity),
      consider whether this page should let you *trigger* a backtest run
      from the UI (pick a strategy/ticker/date range, kick off `backtest()`,
      poll for results) rather than only visualizing runs that were already
      executed from a notebook/script.

---
