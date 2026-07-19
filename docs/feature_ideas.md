# Feature ideas

Running notes on features we want to build later. Not a spec — just enough
context so we can pick a thread back up without re-deriving it. Add a new
`##` section per feature; check items off or delete them once they land.

---

## Regime filter / multi-timeframe direction vs timing

Source: `main_py_refactor_suggestions.md` §2.

Right now each strategy (`MACDStrategy`, `RSIStrategy`, `MovingAverageStrategy`,
and eventually `Momentum` in `src/strategies/momentum.py`) generates a signal
off a single timeframe with no sense of the broader trend. The idea: separate
*direction* (is this ticker trending up on a slow timeframe?) from *timing*
(does the fast timeframe say enter now?) — a strategy should only act on its
own signal if the slow-timeframe filter agrees.

- [ ] Decide where the regime check lives: a shared helper (e.g.
      `in_uptrend(df)` checking daily MA ribbon 50>100>200) that any strategy
      can call, vs. baking it into `base_strategy.py` so every strategy gets
      it by inheritance.
- [ ] `Momentum` (`src/strategies/momentum.py`) is still a stub — this is the
      strategy to build the regime filter into from day one, rather than
      retrofitting it like the other three.
- [ ] Fail-closed: if the slow timeframe can't be computed (not enough
      history, NaNs), default to *not trading* — same guard the reference
      walkthrough uses for `in_uptrend`.
- [ ] Figure out where the second (slower) timeframe's data comes from —
      `cleaner.py`/`fetch_raw_data` currently only pulls one resolution per
      ticker.

---

## Backtest sizing doesn't match live sizing

Source: found while implementing position sizing (`main_py_refactor_suggestions.md`
§3).

Live trading now sizes orders via `trader.size_position(account, current_price,
strategy.risk_fraction)`. `Strategy.backtest()` in `src/strategies/base_strategy.py`
still hardcodes `quantity=1` for every simulated trade
([base_strategy.py:71](../src/strategies/base_strategy.py#L71)), so backtest
results only validate signal quality, not how the bot actually sizes positions
live. Backtests can't currently tell you whether a strategy's `risk_fraction`
is any good.

- [ ] Figure out what `account`/capital `backtest()` should simulate against
      (it currently tracks `capital` starting from `self.initial_capital`,
      no Alpaca account object) so it can call the same sizing formula.
- [ ] Decide whether `size_position` needs a variant that takes plain capital
      instead of an Alpaca `account` object, so backtest and live can share it
      without backtest needing a fake account.

---

## Audit silently-swallowed exceptions

Source: `main_py_refactor_suggestions.md` §4 (second half — the `has_position()`
broad-`APIError` fix is already done).

Sweep the codebase for `except Exception as e:` (and similarly broad catches)
where `e` is never logged — a caught-but-unlogged exception means the bot goes
quiet with no trace of why. Deliberately deferred until after the `main.py`
refactor, since decomposing `run()` into `evaluate_and_trade(...)` +
`DailyRiskState` will likely change where/how exceptions get caught anyway —
no point auditing handlers that are about to move.

- [ ] Grep for `except Exception` / bare `except:` across `src/` once the
      refactor lands, and check each one either logs `e` or has a clear reason
      not to.

---

## Allow same-day re-entry after a completed round-trip

Source: `main_py_refactor_suggestions.md` §5.

`DailyRiskState.signals_executed_today` currently allows exactly one round-trip
(one buy, one sell) per `(ticker, strategy_name)` per day — confirmed
intentional (see docstring on `DailyRiskState` in `src/risk.py`), not a bug.
Blocking re-entry protects against whipsaw and keeps the `is_halted()` ROI
check from being diluted by repeated re-entries inflating `strategy_cost_basis`.

Revisit once these two exist, since they're what would make a second same-day
entry a genuinely distinct setup rather than noise:
- [ ] Regime filter (see "Regime filter / multi-timeframe direction vs
      timing" above) — confirms a new entry lines up with the broader trend,
      not just a signal flicker.
- [ ] Per-trade stop-loss / bracket orders (§3, `trader.py` TODO) — caps
      downside per entry so repeated entries can't compound losses the way
      they could today.

---
