# Noctis

Algorithmic day-trading bot (Python, Alpaca, Azure SQL). The owner reviews everything Claude writes and makes every commit.

## Hard rules

- **Tests first.** For new code and bug fixes: write the test, run it, see it fail for the right reason, then write the code.
- **No profit math on real data.** Never total the owner's real profit, P&L, account size or spending (for example from fill prices × quantities) unless asked. Debug mechanics instead: counts, states, timings, which price was used. Made-up numbers in tests are fine.
- **Never run the bot or `scripts/`, never read `.env*`, never commit.** `.claude/settings.json` blocks these on purpose. Don't work around a block; say what you needed and why.
- **Never crash at startup.** A bad strategy or setting is skipped, recorded in `bot_events`, and alerted with `send_critical`. The rest of the bot keeps running.
- **PowerShell:** never read a file with `Get-Content` and write it back (PowerShell 5.1 double-encodes UTF-8). Use Edit/Write, or Python with `encoding="utf-8"`. A hook blocks it.

## Workflow

- **Status:** `docs/redesign_plan.md`, section "Where we left off" (its `*Updated <date>.*` summary). `/wrap-up` keeps it current.
- **Never read `docs/redesign_plan.md` whole** (about 90k tokens): Grep it, or read only the lines you need.
- Branch off `redesign` (`feat/`, `chore/`, `hook/`). PRs target `redesign`, not `main`, until the redesign ends.

## Database

- **Real data only through the reader helper:** `.\venv\Scripts\python.exe .claude/tools/read_db.py "SELECT ..." [--db dev]`. One SELECT per call, 200-row cap, runs as `claude_reader`. Name the columns: `SELECT *` and `COUNT(*)` are refused on tables with hidden columns.

- New migration: `sql/migrations/NNN_name.sql`, then add it to `BUILD_FILES` in `tests/integration/conftest.py`. `views.sql` runs after every migration.
- **Grants:** a new table gets its `bot_role` grants (INSERT / UPDATE / DELETE as needed) in the same migration that creates it; SELECT comes from the schema-wide grant. Append-only tables get `DENY UPDATE, DELETE`. Dev hides a missing grant (you're the owner there); prod fails with "permission denied".
- **Reader role.** Granting a view grants every column it shows, so never grant `claude_reader_role` a view that reads a hidden column. Every new table or column goes into one of the lists in `tests/integration/test_claude_reader_permissions.py`. The guard tests fail until it does.

## Design rules

- **Settings-driven:** one setting change reconfigures everything that depends on it (example: `MARKET_DATA_PLAN`). No scattered constants.
- **Front doors:** each package exposes a narrow entry point in its `__init__.py`. The rest of the bot never reaches inside. Seams the plan names (swappable sizer, parameter providers, settings switches) are intentional even with one implementation.
- **ML-ready:** save the inputs known at decision time, make the outcome joinable to them, and record who or what decided (provider, version).
- **Day trading first:** anything that differs between day and swing trading is chosen by holding type or a named setting, never hard-coded as "day".
- **Asset class:** the final bot trades stocks (day and swing) and options. Anything that differs between stocks and options (symbol format, quantity unit and multiplier, exits, risk, market data, expiry events) is chosen by asset class, never hard-coded as shares. Options come after the live data plan (OPT tickets in the plan).
- **Alpaca clients:** build every client through `alpaca_client.py`, so the rate limiter is attached. A client built directly skips the limiter and `api.log`.
- **Secrets:** a new secret in `.env` goes into `MASK_ENV_VARS` in `settings.py`, or it isn't masked. Text sent anywhere other than logging or `notifications` passes through `logger.redact()` first.
- **No surprises on import:** importing a file never connects to anything. Clients are built in `main.py` and passed in.
- **Strategies only decide:** data in, signal out. No database, no API calls, and they never read the clock (the engine stamps the time).
- **Same code everywhere:** live trading, backtests and ML training use the same strategies, features, sizing and risk rules.
- **Storage functions take `conn` and never commit.** The caller owns the transaction.

## Trading safety

- **Protection map:** `docs/protections.md` lists every choke point (orders, cancels, fills, clients) and its only callers. A branch that adds a protection or a new path to Alpaca or the trade tables updates it. The `trading-safety-reviewer` agent checks branches against it.

- **Alpaca is the source of truth:** every fill at Alpaca exists in the database exactly once, with its strategy and position. The one exception until options are supported (OPT tickets): an option fill is kept raw only and flagged (`docs/protections.md`, "Every fill exactly once").
- **Nothing important lives only in memory:** a restart rebuilds state from the database and Alpaca. One bad ticker never stops the cycle.
- **Sells are never blocked:** the kill switch, halts, audit blocks and guardrails stop buys only. Exits always run.
- **Hard limits are human-set:** a model may take over a tunable value within its bounds, never a hard limit. Admin-only columns (`budget`, `mode`, `fill_override`) are never changed by the bot.
- **Alert on change, not every cycle:** one alert when something breaks and one when it recovers.

## Data

- **Save raw first, then handle:** outside events (stream messages, account activities) are saved untouched before any processing.
- **Append-only records:** `trades`, `broker_events` and `account_activities` are never updated; a correction is a new row.
- **Derived values live in views, never stored:** counts and P/L are calculated, so they can't drift. Power BI reads only views.
- **UTC everywhere:** store UTC; convert to Eastern only for the schedule and for display.
- **Market data:** SIP volume only, closed candles only; IEX only as "where is the price now".

## Style

- Follow `docs/code_style.md` for new or changed lines. Don't flag style in code the branch didn't touch.
- Before calling code done, check each new or changed function against the "Failure checklist" in `docs/code_style.md`.
- Comment only when the code can't be understood without it. Design reasons go in the docs.
- Versions are always three parts: `"1.0.0"`.
- Files written by scripts go in `scripts/reports/`. `logs/` holds only the app's `.log` files.

## Commands

- Secret scan on every commit: `pre-commit` runs gitleaks (`.pre-commit-config.yaml`). Once per clone: install gitleaks (`winget install Gitleaks.Gitleaks`), then `.\venv\Scripts\pre-commit.exe install`. A finding blocks the commit; remove the secret, never skip the hook.
- Unit tests: `pytest tests/unit`
- Integration tests: `pytest tests/integration`. They need SQL Server Express at `localhost\SQLEXPRESS` (override with `TEST_DB_SERVER`). They rebuild a throwaway `noctis_test` database and never read `.env`.

## Docs (local only, `docs/` is git-ignored)

- `docs/redesign_plan.md`: the plan and its decisions. Until `docs/adr/` exists, treat its decisions as ADRs.
- `docs/<module>.md`: beginner guide per module. Update it when the module changes.
- `docs/test_reasons.md`: how to decide which tests a change needs.
