# Algorithmic Trading Bot

A Python trading bot that screens for momentum stocks, evaluates them against
several trading strategies, and places paper trades through Alpaca. It logs
every trade and backtest run to an Azure SQL database and ships with a small
FastAPI + static-HTML dashboard for reviewing activity.

## How it works

1. **Screen** — `src/screener.py` queries the TradingView scanner for tickers
   matching `DEFAULT_FILTERS` in [src/config.py](src/config.py) (price range,
   % change, relative volume, float size). The screener refreshes once daily
   at market open.
2. **Load data** — `src/cleaner.py` pulls and cleans OHLCV data per ticker.
3. **Evaluate strategies** — every ticker in the screener cache is run through
   each strategy on a schedule tied to market hours
   ([src/market_hours.py](src/market_hours.py)):
   - **MACD** ([src/strategies/macd.py](src/strategies/macd.py))
   - **RSI** ([src/strategies/rsi.py](src/strategies/rsi.py))
   - **Moving Average Crossover** ([src/strategies/moving_average.py](src/strategies/moving_average.py))
   - **Momentum** (Warrior Trading style bull flag / flat top breakouts —
     [src/strategies/momentum.py](src/strategies/momentum.py))
   - **ICT Liquidity Sweep** (liquidity sweep, change of character, fair
     value gap — [src/strategies/ict.py](src/strategies/ict.py))

   All strategies share a common interface defined in
   [src/strategies/base_strategy.py](src/strategies/base_strategy.py), which
   also implements the backtesting loop.
4. **Size and place orders** — `src/risk.py` tracks daily risk state (one
   round-trip per ticker/strategy/day, profit target / loss limit halts) and
   `src/trader.py` sizes and submits orders through the Alpaca API
   ([src/alpaca_client.py](src/alpaca_client.py)).
5. **Persist and notify** — every order, trade, and backtest metric is
   written to Azure SQL via `src/db.py` (schema in
   [sql/schema.sql](sql/schema.sql)), and Discord webhooks
   (`src/notifications.py`) report routine status, trade fills, and critical
   errors.

The bot currently trades on Alpaca's paper trading endpoint.

## Project layout

```
src/                  Bot source code
  main.py             Scheduler entry point — runs the bot on market hours
  strategies/          One module per trading strategy + shared base class
  patterns/            Candlestick / price-action pattern detectors
  indicators/          Technical indicator implementations
  screener.py          TradingView-based ticker screener
  cleaner.py           OHLCV data fetching/cleaning
  trader.py            Order placement and position sizing
  risk.py              Daily risk state and halting logic
  db.py                Azure SQL persistence layer
  alpaca_client.py     Alpaca API client
  market_hours.py      Market-hours/schedule helpers
  notifications.py     Discord webhook notifications
  logger.py            Logging setup
  config.py            Global settings (filters, risk defaults)
sql/schema.sql          Azure SQL schema (Orders, Trades, Metrics, ...)
website/
  backend/             FastAPI app serving trade/expense dashboards
  frontend/            Static HTML dashboard pages
notebooks/             Exploratory/backtesting notebooks
docs/feature_ideas.md   Running notes on planned features
```

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv venv
   venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:

   ```bash
   cp .env.example .env
   ```

   - **Alpaca** — API key/secret for paper trading (`ALPACA_BASE_URL` should
     point at `paper-api.alpaca.markets`).
   - **Discord** — webhook URLs for critical, trade, and routine
     notifications.
   - **Azure SQL** — server, database, user, and password for trade/metrics
     storage. Run [sql/schema.sql](sql/schema.sql) against the database
     before first use.

3. Run the bot:

   ```bash
   python src/main.py
   ```

   This starts a scheduler that refreshes the screener at market open, runs
   strategy evaluation on a recurring interval during market hours, and sends
   daily open/close status notifications.

## Dashboard (optional)

A FastAPI backend and static frontend for reviewing trades/expenses live
under `website/`:

```bash
pip install -r website/backend/requirements.txt
cd website/backend
uvicorn main:app --reload
```

## Status

This is an active, personal project — see
[docs/feature_ideas.md](docs/feature_ideas.md) for planned work (regime
filters, backtest/live sizing parity, exception auditing, and more).
