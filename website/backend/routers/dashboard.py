from fastapi import APIRouter
from statistics import mean, pstdev
from math import sqrt
from database import get_connection, run_query, run_query_params

router = APIRouter()


@router.get("/api/dashboard")
def get_dashboard(strategy: str = "all", symbol: str = "all"):
    with get_connection() as conn:
        filters = []
        params = []
        if strategy != "all":
            filters.append("Strategy = ?")
            params.append(strategy)
        if symbol != "all":
            filters.append("Ticker = ?")
            params.append(symbol)
        where_clause = ("AND " + " AND ".join(filters)) if filters else ""

        trades_query = f"""
            SELECT [Date], Strategy, Ticker, Profit FROM Trades
            WHERE Profit IS NOT NULL {where_clause}
            ORDER BY [Date] ASC;
        """
        trades = run_query_params(conn, trades_query, params)

        starting_capital_query = f"""
            WITH Latest AS (
                SELECT Strategy, Ticker, Starting_Capital,
                       ROW_NUMBER() OVER (PARTITION BY Strategy, Ticker ORDER BY [Date] DESC) AS rn
                FROM Metrics
                WHERE 1 = 1 {where_clause}
            )
            SELECT ISNULL(SUM(Starting_Capital), 0) AS StartingCapital FROM Latest WHERE rn = 1;
        """
        starting_capital = run_query_params(conn, starting_capital_query, params)[0]["StartingCapital"]

        strategy_options = [r["Strategy"] for r in run_query(conn, "SELECT DISTINCT Strategy FROM Trades ORDER BY Strategy;")]
        symbol_options = [r["Ticker"] for r in run_query(conn, "SELECT DISTINCT Ticker FROM Trades ORDER BY Ticker;")]

    daily = {}
    strategy_pl = {}
    symbol_pl = {}
    wins = 0
    losses = 0
    for t in trades:
        profit = float(t["Profit"])
        day_key = t["Date"].date() if hasattr(t["Date"], "date") else t["Date"]
        daily[day_key] = daily.get(day_key, 0.0) + profit
        strategy_pl[t["Strategy"]] = strategy_pl.get(t["Strategy"], 0.0) + profit
        symbol_pl[t["Ticker"]] = symbol_pl.get(t["Ticker"], 0.0) + profit
        if profit > 0:
            wins += 1
        elif profit < 0:
            losses += 1

    sorted_days = sorted(daily.keys())
    dates = [f"{d.strftime('%b')} {d.day}" for d in sorted_days]
    daily_pl = [daily[d] for d in sorted_days]

    cumulative_pl = []
    running = 0.0
    for v in daily_pl:
        running += v
        cumulative_pl.append(running)
    equity = [float(starting_capital) + c for c in cumulative_pl]

    max_drawdown = 0.0
    if equity:
        peak = equity[0]
        for e in equity:
            if e > peak:
                peak = e
            if peak > 0:
                dd = (e - peak) / peak
                if dd < max_drawdown:
                    max_drawdown = dd

    if len(daily_pl) > 1 and pstdev(daily_pl) > 0:
        sharpe = (mean(daily_pl) / pstdev(daily_pl)) * sqrt(252)
    else:
        sharpe = 0.0

    trade_profits = [float(t["Profit"]) for t in trades]
    win_profits = [p for p in trade_profits if p > 0]
    loss_profits = [p for p in trade_profits if p < 0]
    gross_profit = sum(win_profits)
    gross_loss = abs(sum(loss_profits))
    avg_win = mean(win_profits) if win_profits else 0.0
    avg_loss = abs(mean(loss_profits)) if loss_profits else 0.0

    if not trades:
        risk = {"maxDrawdown": "—", "sharpe": "—", "profitFactor": "—", "avgWinLoss": "—"}
    else:
        profit_factor_text = "—"
        if gross_loss > 0:
            profit_factor_text = f"{gross_profit / gross_loss:.2f}"
        elif gross_profit > 0:
            profit_factor_text = "∞"

        avg_win_loss_text = f"{avg_win / avg_loss:.1f} : 1" if avg_loss > 0 else "—"

        risk = {
            "maxDrawdown": f"{max_drawdown * 100:.1f}%",
            "sharpe": f"{sharpe:.2f}",
            "profitFactor": profit_factor_text,
            "avgWinLoss": avg_win_loss_text,
        }

    return {
        "risk": risk,
        "dates": dates,
        "equity": equity,
        "cumulativePL": cumulative_pl,
        "dailyPL": daily_pl,
        "strategies": strategy_pl,
        "symbols": symbol_pl,
        "winLoss": {"wins": wins, "losses": losses},
        "strategyOptions": strategy_options,
        "symbolOptions": symbol_options,
    }
