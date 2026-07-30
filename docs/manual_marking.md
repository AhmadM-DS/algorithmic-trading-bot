# Manual chart marking (entries/exits)

Goal: click a candle on a chart, get an OHLC popup, tag it as a buy/sell
entry or exit, and have that write out to a **training dataset** for a
machine learning model — not just a backtest log. The candle info alone
(ticker, date, OHLC) isn't enough to train on; the row needs to capture the
same features the model will see at inference time (timeframe, indicator
values, volume, surrounding context), plus the label itself (entry/exit,
side, and ideally an outcome). This doc is the full implementation plan —
architecture, schema, step-by-step build, and tradeoffs.

Not started yet. Nothing below is built.

---

## A note on the database

`website/backend/database.py` connects via `pyodbc` + `ODBC Driver 18 for
SQL Server` to `DB_SERVER=trading-bot-sql-am.database.windows.net` (see
`.env`). That hostname is **Azure SQL Database** — Microsoft's managed,
cloud-hosted SQL Server engine. It is not a different database technology
from "SQL Server"; it's the same T-SQL engine as PaaS, just not a
self-hosted instance. So "SQL Server" in this doc and "my database is in
Azure" are the same thing — the `MarkedTrades` table and `pyodbc` queries
below work against your existing Azure SQL DB with zero changes. No new
database, driver, or connection method needed.

---

## Why build this instead of using an existing tool

TradingView (manual replay + notes) or a spreadsheet workflow both work
today with zero build cost. The reason to build a custom tool is that
neither produces a clean, structured **training dataset** — you'd still
have to hand-transcribe ticker/OHLC/indicator values/labels into a schema
the model can load. A custom labeler makes the *output format* the point,
not the charting itself: every mark should come out already shaped as a
feature row + label, ready for `docs/machine_learning_future.md`'s pipeline.

If the real goal is just "eyeball some setups quickly," don't build this —
use TradingView. Build this only if you expect to label enough trades
(hundreds+) that a few hours of setup pays for itself in click-speed and in
producing model-ready rows instead of a spreadsheet you'd still have to
clean up.

---

## Architecture

Reuse the existing stack in `website/` rather than starting a new app:

- **Frontend**: new static page `website/frontend/marking.html` +
  `website/frontend/js/marking.js`, following the pattern of
  `tradelogs.html`/`tradelogs.js`.
- **Chart library**: [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)
  (Apache-2.0, free, no account needed). It's built specifically for
  candlestick series with a `subscribeClick` event that gives you the
  clicked bar's time/OHLC directly — no need to hit-test pixel coordinates
  yourself.
- **Backend**: new router `website/backend/routers/marking.py`, registered
  in `main.py` alongside the existing routers. Follows the same
  `pyodbc` + `run_insert`/`run_query_params` pattern already in
  `database.py` — no new DB technology.
- **Storage**: new table `MarkedTrades` in the existing Azure SQL Database
  (see "A note on the database" above — same DB the `Trades` table already
  lives in per `database.py`). Keeping it in the same DB means the
  "separate script" the user describes can just query it directly with
  `run_query`, same as any other report, and it's one less thing to
  provision.
- **Data source for candles + features**: reuse `src/alpaca_client.py` /
  `src/cleaner.py`'s historical-bar fetch (already pulls OHLCV from
  Alpaca) behind a small `GET /marking/candles?ticker=...&start=...&end=...`
  endpoint that returns JSON in the shape Lightweight Charts expects
  (`{time, open, high, low, close}` per bar), **plus** the indicator values
  from `src/indicators/technical_indicators.py` (RSI, EMA, MACD, VWAP —
  same classes the live strategies use) computed over that same range, so
  the popup and the saved row both have real feature values, not just
  price. Don't hand-roll a second data fetcher or a second indicator
  implementation — reuse both.

```
[marking.html]
     |  loads candles
     v
GET /marking/candles?ticker=SPY&tf=1D&start=...&end=...
     |  (wraps existing Alpaca historical-bar fetch)
     v
[Lightweight Charts renders candlesticks]
     |  user clicks a candle -> subscribeClick fires with OHLC + time
     v
[popup form: trade type (entry/exit), side (buy/sell), strategy/tag, notes]
     |  user confirms
     v
POST /marking/label  { ticker, date, open, high, low, close, side, trade_type, tag, notes }
     v
[MarkedTrades table in SQL Server]
     |
     v
[separate backtesting script reads MarkedTrades via run_query()]
```

---

## Data model

The columns below split into two groups: **features** (what the model sees
as input — must be computable identically at training time and at live
inference time) and **label** (what the model is trying to predict). Mixing
these up is the most common mistake in hand-built ML datasets, so the
schema keeps them visually separate.

```sql
CREATE TABLE MarkedTrades (
    ID INT IDENTITY(1,1) PRIMARY KEY,

    -- ===== identity / context =====
    Ticker VARCHAR(10) NOT NULL,
    Bar_Date DATETIME2 NOT NULL,        -- the clicked candle's timestamp
    Timeframe VARCHAR(10) NOT NULL,     -- e.g. '1D', '1H', '5Min' -- REQUIRED:
                                         -- a model trained on daily setups
                                         -- won't transfer to 5-min candles,
                                         -- so every row must record which
                                         -- resolution it was labeled on.

    -- ===== features (must match what's computable live, see below) =====
    [Open] FLOAT NOT NULL,
    High FLOAT NOT NULL,
    Low FLOAT NOT NULL,
    [Close] FLOAT NOT NULL,
    Volume BIGINT NULL,
    RSI_14 FLOAT NULL,                  -- from indicators.RSI, same period
                                         -- the live strategies use
    EMA_9 FLOAT NULL,
    EMA_21 FLOAT NULL,
    MACD_Line FLOAT NULL,
    MACD_Signal FLOAT NULL,
    MACD_Histogram FLOAT NULL,
    VWAP FLOAT NULL,
    Lookback_Bars_JSON NVARCHAR(MAX) NULL,  -- OHLCV of the preceding N
                                             -- candles (e.g. N=10), so the
                                             -- model can see the pattern
                                             -- leading into the marked bar,
                                             -- not just one candle in
                                             -- isolation

    -- ===== label (the target) =====
    Side VARCHAR(4) NOT NULL,           -- 'BUY' or 'SELL'
    Trade_Type VARCHAR(10) NOT NULL,    -- 'ENTRY' or 'EXIT'
    Strategy_Tag VARCHAR(50) NULL,      -- optional: which setup this is for
                                         -- (useful if labeling multiple
                                         -- distinct patterns for
                                         -- multi-class training later)
    Outcome_R_Multiple FLOAT NULL,      -- filled in once the paired
                                         -- entry/exit is known: realized
                                         -- (exit - entry) / risk. Lets the
                                         -- model be trained as a regressor
                                         -- on expected quality, not just a
                                         -- binary "was this a trade" class.
    Notes VARCHAR(250) NULL,

    -- ===== bookkeeping =====
    Session_ID VARCHAR(50) NULL,        -- groups an entry with its matching exit
    Created_At DATETIME2 DEFAULT SYSUTCDATETIME()
);
```

**Why the features have to be computed the same way live**: if
`RSI_14`/`EMA_9`/etc. in this table are computed with different logic than
`src/indicators/technical_indicators.py` uses in live trading (different
smoothing, different warm-up handling), the model will train on a
distribution of feature values it will never actually see at inference
time — a classic train/serve skew bug. That's why the candle-fetch endpoint
should call the *same* `RSI`/`EMA`/`MACD`/`VWAP` classes, not a
reimplementation.

**`Lookback_Bars_JSON`**: stored as JSON rather than N separate columns
because the lookback window size is likely to change as you experiment
(5 bars vs. 20 bars) — a JSON blob avoids a schema migration every time you
want to try a different window. The export script (below) is what expands
it into fixed-width feature columns for whatever training format you use
(e.g. one row per bar in a wide DataFrame).

`Session_ID` is worth calling out: a lone table of entry/exit rows doesn't
tell a backtest script which exit belongs to which entry. Two options:

1. Generate a `Session_ID` (UUID) client-side when the user marks an entry,
   and require them to click "attach to open trade" when marking the
   matching exit. More clicks, unambiguous data.
2. Skip `Session_ID` and reconstruct pairs later in the consuming script by
   sorting `(Ticker, Bar_Date)` and pairing entries with the next exit.
   Zero extra clicks, but silently wrong if trades overlap (two open
   positions on the same ticker) or a click is missed.

Recommendation: implement (1). The extra click per trade is cheap compared
to debugging mismatched entry/exit pairs in a backtest later.

Matching Pydantic model in `website/backend/models.py`:

```python
class MarkedTradeCreate(BaseModel):
    Ticker: str = Field(min_length=1, max_length=10)
    Bar_Date: datetime
    Timeframe: str = Field(min_length=1, max_length=10)

    # features
    Open: float
    High: float
    Low: float
    Close: float
    Volume: Optional[int] = None
    RSI_14: Optional[float] = None
    EMA_9: Optional[float] = None
    EMA_21: Optional[float] = None
    MACD_Line: Optional[float] = None
    MACD_Signal: Optional[float] = None
    MACD_Histogram: Optional[float] = None
    VWAP: Optional[float] = None
    Lookback_Bars: Optional[list[dict]] = None  # serialized to JSON on insert

    # label
    Side: Literal["BUY", "SELL"]
    Trade_Type: Literal["ENTRY", "EXIT"]
    Strategy_Tag: Optional[str] = None
    Outcome_R_Multiple: Optional[float] = None
    Notes: Optional[str] = Field(default=None, max_length=250)
    Session_ID: Optional[str] = None
```

The frontend doesn't need the user to type indicator values by hand — the
`/marking/candles` response already includes them per-bar (see below), so
`marking.js` just copies the clicked bar's precomputed values into the
POST body. The only fields the user actually fills in via the popup/
shortcuts are `Side`, `Trade_Type`, `Strategy_Tag`, and `Notes`.

---

## Step-by-step implementation

1. **Migration**: add the `MarkedTrades` table (SQL script or manual, same
   as however `Trades`/`Subscriptions` were created — there's no migration
   framework in this repo currently).
2. **Backend route** `website/backend/routers/marking.py`:
   - `GET /marking/candles` — wraps existing Alpaca historical-bar fetch for
     a ticker/timeframe/date range, then runs the fetched bars through
     `RSI`, `EMA(9)`, `EMA(21)`, `MACD`, `VWAP` from
     `src/indicators/technical_indicators.py` and returns each bar with its
     indicator values attached, plus a `lookback` array of the preceding N
     bars for pattern context.
   - `POST /marking/label` — validates `MarkedTradeCreate`, serializes
     `Lookback_Bars` to JSON, inserts a row via `run_insert`.
   - `GET /marking/labels?ticker=...` — lists existing marks so the chart
     can re-render prior labels (little markers on already-marked candles)
     when you reopen a ticker.
   - `DELETE /marking/labels/{id}` — for fixing mis-clicks.
3. **Register the router** in `website/backend/main.py` (one line, same
   pattern as the other five routers).
4. **Frontend page** `marking.html` + `marking.js`:
   - Ticker/date-range/timeframe picker at the top (reuse whatever
     select/input styling `dashboard.html` already uses).
   - Lightweight Charts candlestick series filled from `/marking/candles`.
   - `chart.subscribeClick(param => ...)` handler: look up the bar at
     `param.time`, open a small popup (plain HTML `<dialog>` or a
     lightweight modal, no need for a framework) pre-filled with
     ticker/date/OHLC (read-only) plus fields for side, trade type,
     strategy tag, notes.
   - On submit: `POST /marking/label`, then draw a marker on that candle
     (Lightweight Charts supports `setMarkers()`) so marked candles are
     visually distinct without re-fetching.
   - Keyboard shortcuts for speed (see below) instead of forcing every mark
     through the popup.
5. **Consumer script**: a small `scripts/export_marked_trades.py` that runs
   `run_query(conn, "SELECT * FROM MarkedTrades ORDER BY Ticker, Bar_Date")`,
   expands `Lookback_Bars_JSON` into flat feature columns, and writes out a
   training-ready file (CSV/Parquet, or directly into whatever your model
   training code loads) — this is the "separate script" from the original
   request, now specifically an ML feature-export step rather than a
   backtest-log dump. Keep it separate from the web app; it's a one-off
   ETL, not a route.
6. **Backfill `Outcome_R_Multiple`**: once an entry's paired exit is marked
   (same `Session_ID`), a small trigger/scheduled query can compute
   `(exit_price - entry_price) / risk` and update both rows — gives the
   model a continuous quality target instead of a bare buy/sell class.

---

## Speed optimizations (the actual ask: "how do I speed this up")

- **Keyboard shortcuts instead of mouse-driven popups for the common case.**
  Click a candle to select it, then a single keypress commits the label:
  `B` = buy entry, `S` = sell entry, `X` = exit (paired to most recent open
  session on that ticker), `Esc` = cancel. Reserve the full popup form for
  when you need to set a strategy tag or notes. This alone cuts most marks
  from "click → fill form → click submit" to "click → keypress."
- **Auto-pair exits.** Track "open sessions" (entries without a matching
  exit) client-side per ticker. When the user marks an exit, don't ask
  which entry it closes — default to the most recent open one on that
  ticker and let them override only if wrong.
- **Persist the last-used strategy tag** and pre-fill it, since you're
  usually labeling a batch of trades for the same setup in one sitting.
- **Prefetch adjacent date ranges** so paging forward/backward through a
  ticker's history doesn't wait on a network round-trip each time.
- **Batch-render existing markers on load** (`setMarkers()` once, not per
  candle) so reopening a previously-marked ticker doesn't feel slow.
- **Undo, not confirm dialogs.** A confirm-before-submit dialog doubles
  every click. Instead, submit immediately and show a toast with an "undo"
  button that calls `DELETE /marking/labels/{id}` for a few seconds after.
- Optional bigger lift: **multi-monitor / large-batch mode** — a queue of
  tickers to label sequentially with `→`/`←` to move to the next ticker
  once the current one's trades are marked, so you never touch the mouse
  to navigate between symbols.

---

## Implications / things to decide before building

- **This becomes another consumer of `src/alpaca_client.py`'s rate limits.**
  Paging through months of history one ticker at a time during a labeling
  session adds API calls on top of whatever the live bot is doing. Fine at
  low volume; worth caching bars locally (e.g. to disk/SQLite) if labeling
  sessions get long, so re-opening a ticker doesn't re-hit Alpaca.
- **Label quality is inherently subjective.** Hindsight-marked entries/exits
  on a static chart are easier to get "clean" than what a live strategy
  could actually have detected in real time (no lookahead bias guard here
  unless you deliberately hide future bars while marking). If the eventual
  goal is training a model or validating a strategy, decide up front
  whether labels need to be blind to future candles (harder to build: chart
  would need to reveal bars progressively) or whether hindsight labeling is
  acceptable (e.g. just building a "what a good trade looks like" reference
  set, not simulating real-time decision-making).
- **No auth on `website/backend` currently** (`CORSMiddleware` is wide open,
  per the `# CHANGE * IN ALLOW ORIGINS` comment in `main.py`). Fine for
  solo local use; if this ever runs anywhere reachable beyond localhost,
  the marking endpoints need the same access control as everything else in
  that app (currently none — flag this if `website/backend` ever gets
  deployed).
- **Schema lock-in.** Whatever columns you pick in `MarkedTrades` become
  the contract the export script and eventually the model's feature
  pipeline depend on. Prefer adding nullable columns later over
  renaming/removing once you've labeled a batch of trades — otherwise
  re-labeling sessions get invalidated.
- **Train/serve skew.** As called out in the schema section: indicator
  features stored here must be computed by the same code path the live
  bot uses (`src/indicators/technical_indicators.py`), or the model learns
  a feature distribution it'll never see in production. This is the single
  biggest risk to the "better train my ML model" goal — worth double
  checking whenever an indicator's calculation changes.
- **Class imbalance by construction.** You'll naturally mark far more
  "good" entries than bad ones (nobody manually labels a trade they'd
  never take), so a dataset built purely from `MarkedTrades` skews
  positive. If the model needs negative examples (setups that looked
  plausible but weren't good entries), that has to be a deliberate labeling
  pass, not a side effect of this tool.

---

## Pros / cons

**Pros**
- Structured, queryable dataset from the start — no manual transcription
  step between "I looked at a chart" and "this is a row a script can read."
- Reuses existing infra end-to-end (FastAPI router pattern, `database.py`
  helpers, Alpaca client, static frontend) — no new services, no new DB.
- Keyboard-driven flow scales to labeling hundreds of trades without the
  process getting tedious.
- Markers persist and re-render, so labeling can happen incrementally
  across multiple sessions per ticker.

**Cons**
- Real build cost: new table, new router, new page, new JS — likely a full
  day including the popup/shortcut UX, not a quick script.
- Yet another thing to maintain in `website/` (currently the least-tested
  part of the repo — no test coverage under `website/backend`).
- Manual labels carry human bias/hindsight and are not a substitute for
  proper walk-forward backtesting; useful as a reference/training set, not
  as validation of a strategy's live performance.
- Adds Alpaca API load during labeling sessions on top of the bot's own
  usage.

---

## Effort estimate

- Table + Pydantic model: ~30 min.
- `GET /marking/candles` (wrapping existing fetch + running
  RSI/EMA/MACD/VWAP + building the lookback window): ~1 hr.
- `POST/GET/DELETE` label routes: ~45 min.
- Frontend page with Lightweight Charts + click popup: ~2–3 hrs (most of
  the effort — chart wiring, popup, markers).
- Keyboard-shortcut fast path: ~1 hr on top of the basic popup flow.
- Export script (flatten `Lookback_Bars_JSON`, write training-ready
  file): ~45 min.

Rough total: **~1 day** for a working v1 (popup-only, no shortcuts);
**~1.5 days** with the keyboard-shortcut speed path included.

---

## Open questions

- [ ] Does labeling need to be lookahead-safe (progressive bar reveal), or
      is hindsight labeling acceptable for the intended use case?
- [ ] Timeframe(s) to support — just daily, or intraday too? Affects the
      candle-fetch endpoint and how much Alpaca data gets pulled per
      session.
- [ ] Where should the exported labels ultimately land — fed straight into
      `Strategy.backtest()` as synthetic signals, or into a separate
      ML dataset per `docs/machine_learning_future.md`?
- [ ] How big should the lookback window (`Lookback_Bars_JSON`) be, and does
      it need to match whatever window size the model architecture expects
      (e.g. a fixed sequence length for an RNN/transformer vs. flattened
      features for a gradient-boosted tree)?
- [ ] Does the model need negative examples (marked "not a good setup")
      alongside positive entries/exits, and if so does the popup need a
      third label option for that, or is a separate labeling pass better?
