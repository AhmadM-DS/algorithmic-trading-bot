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
- Branch off `redesign` (`feat/`, `chore/`, `hook/`). PRs target `redesign`, not `main`, until the redesign ends.

## Database

- **Real data only through the reader helper:** `.\venv\Scripts\python.exe .claude/tools/read_db.py "SELECT ..." [--db dev]`. One SELECT per call, 200-row cap, runs as `claude_reader`. Name the columns: `SELECT *` and `COUNT(*)` are refused on tables with hidden columns.

- New migration: `sql/migrations/NNN_name.sql`, then add it to `BUILD_FILES` in `tests/integration/conftest.py`. `views.sql` runs after every migration.
- **Reader role.** Granting a view grants every column it shows, so never grant `claude_reader_role` a view that reads a hidden column. Every new table or column goes into one of the lists in `tests/integration/test_claude_reader_permissions.py`. The guard tests fail until it does.

## Design rules

- **Settings-driven:** one setting change reconfigures everything that depends on it (example: `MARKET_DATA_PLAN`). No scattered constants.
- **Front doors:** each package exposes a narrow entry point in its `__init__.py`. The rest of the bot never reaches inside. Seams the plan names (swappable sizer, parameter providers, settings switches) are intentional even with one implementation.
- **ML-ready:** save the inputs known at decision time, make the outcome joinable to them, and record who or what decided (provider, version).
- **Day trading first:** anything that differs between day and swing trading is chosen by holding type or a named setting, never hard-coded as "day".

## Style

- Follow `docs/code_style.md` for new or changed lines. Don't flag style in code the branch didn't touch.
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
