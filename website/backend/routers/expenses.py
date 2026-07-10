from fastapi import APIRouter
from database import get_connection, run_query

router = APIRouter()

@router.get("/api/expenses")
def get_expense():
    with get_connection() as conn:
        subscriptions_query = """SELECT [Service_Name], [Provider], Purpose, Cost, Billing_Cycle, 
                                    Payment_Method, [Start_Date], Is_Active FROM Subscriptions;"""
        expenses_query = """SELECT e.[Date], e.Expense_Name, e.[Provider], e.Purpose, e.Cost, 
                                e.Payment_Method, s.[Service_Name] AS [Subscription]
                            FROM Expenses e
                            LEFT JOIN Subscriptions s ON e.Subscription_ID = s.Subscription_ID;"""
        subscriptions = run_query(conn, subscriptions_query)
        expenses = run_query(conn, expenses_query)
    return {
        "subscriptions": subscriptions,
        "expenses": expenses
    }