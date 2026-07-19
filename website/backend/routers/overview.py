from fastapi import APIRouter
from database import get_connection, run_query

router = APIRouter()

OPEN_STATUSES = ("new", "pending", "partially_filled", "accepted")


@router.get("/api/account-overview")
def get_account_overview():
    with get_connection() as conn:
        starting_capital_query = """
            WITH Latest AS (
                SELECT Starting_Capital,
                       ROW_NUMBER() OVER (PARTITION BY Strategy, Ticker ORDER BY [Date] DESC) AS rn
                FROM Metrics
            )
            SELECT ISNULL(SUM(Starting_Capital), 0) AS StartingCapital FROM Latest WHERE rn = 1;
        """
        total_profit_query = """
            SELECT ISNULL(SUM(Profit), 0) AS TotalProfit FROM Trades WHERE Profit IS NOT NULL;
        """
        daily_pl_query = """
            SELECT ISNULL(SUM(Profit), 0) AS DailyPL FROM Trades
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE) AND Profit IS NOT NULL;
        """
        win_rate_query = """
            SELECT
                SUM(CASE WHEN Profit > 0 THEN 1 ELSE 0 END) AS Wins,
                COUNT(*) AS Total
            FROM Trades
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE) AND Profit IS NOT NULL;
        """
        trades_today_query = """
            SELECT COUNT(*) AS TradesToday FROM Trades
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE);
        """
        open_positions_query = f"""
            SELECT COUNT(*) AS OpenPositions FROM Orders
            WHERE Status IN ({", ".join("?" * len(OPEN_STATUSES))});
        """
        stocks_today_query = """
            SELECT DISTINCT Ticker, Side FROM Trades
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE);
        """
        strategy_today_query = """
            SELECT Strategy, COUNT(*) AS TradeCount FROM Trades
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE)
            GROUP BY Strategy;
        """
        orders_today_query = """
            SELECT Ticker, Side, Quantity, Price FROM Orders
            WHERE CAST([Date] AS DATE) = CAST(GETDATE() AS DATE)
            ORDER BY [Date] DESC;
        """
        calendar_query = """
            SELECT DAY([Date]) AS Day, SUM(Profit) AS PL
            FROM Trades
            WHERE Profit IS NOT NULL
                AND YEAR([Date]) = YEAR(GETDATE())
                AND MONTH([Date]) = MONTH(GETDATE())
            GROUP BY DAY([Date]);
        """

        starting_capital = run_query(conn, starting_capital_query)[0]["StartingCapital"]
        total_profit = run_query(conn, total_profit_query)[0]["TotalProfit"]
        daily_pl = run_query(conn, daily_pl_query)[0]["DailyPL"]
        win_rate_row = run_query(conn, win_rate_query)[0]
        trades_today = run_query(conn, trades_today_query)[0]["TradesToday"]

        cursor = conn.cursor()
        cursor.execute(open_positions_query, OPEN_STATUSES)
        open_positions = cursor.fetchone()[0]

        stocks_today = run_query(conn, stocks_today_query)
        strategy_today = run_query(conn, strategy_today_query)
        orders_today = run_query(conn, orders_today_query)
        calendar_rows = run_query(conn, calendar_query)

    wins = win_rate_row["Wins"] or 0
    total = win_rate_row["Total"] or 0
    win_rate = round((wins / total) * 100, 1) if total else 0

    return {
        "accountBalance": float(starting_capital) + float(total_profit),
        "dailyPL": float(daily_pl),
        "winRate": win_rate,
        "tradesToday": trades_today,
        "openPositions": open_positions,
        "stocks": [{"symbol": r["Ticker"], "side": r["Side"]} for r in stocks_today],
        "strategy": [
            {"name": r["Strategy"], "detail": f"{r['TradeCount']} trade(s)"}
            for r in strategy_today
        ],
        "orders": [
            {
                "symbol": r["Ticker"],
                "type": f"{r['Side'].title()} {r['Quantity']} @ {float(r['Price']):.2f}",
            }
            for r in orders_today
        ],
        "calendar": {int(r["Day"]): float(r["PL"]) for r in calendar_rows},
    }
