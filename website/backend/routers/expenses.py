from fastapi import APIRouter, HTTPException
from database import get_connection, run_query, run_query_params, run_insert
from models import SubscriptionCreate, ExpenseCreate

router = APIRouter()

@router.get("/api/expenses")
def get_expense():
    with get_connection() as conn:
        subscriptions_query = """SELECT Subscription_ID, [Service_Name], [Provider], Purpose, Cost, Billing_Cycle,
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


@router.post("/api/subscriptions", status_code=201)
def create_subscription(sub: SubscriptionCreate):
    insert_query = """
        INSERT INTO Subscriptions
            ([Service_Name], [Provider], Purpose, Cost, Billing_Cycle, Payment_Method, [Start_Date], Is_Active)
        OUTPUT INSERTED.Subscription_ID
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """
    params = (
        sub.Service_Name, sub.Provider, sub.Purpose, sub.Cost,
        sub.Billing_Cycle, sub.Payment_Method, sub.Start_Date, sub.Is_Active,
    )
    with get_connection() as conn:
        new_id = run_insert(conn, insert_query, params)
    return {"Subscription_ID": new_id}


@router.post("/api/expenses", status_code=201)
def create_expense(exp: ExpenseCreate):
    insert_query = """
        INSERT INTO Expenses
            (Expense_Name, [Provider], Purpose, Cost, Payment_Method, [Date], Subscription_ID)
        OUTPUT INSERTED.Expense_ID
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    params = (
        exp.Expense_Name, exp.Provider, exp.Purpose, exp.Cost,
        exp.Payment_Method, exp.Date, exp.Subscription_ID,
    )
    with get_connection() as conn:
        if exp.Subscription_ID is not None:
            exists = run_query_params(
                conn, "SELECT 1 AS found FROM Subscriptions WHERE Subscription_ID = ?", (exp.Subscription_ID,)
            )
            if not exists:
                raise HTTPException(status_code=400, detail="Subscription_ID does not exist")
        new_id = run_insert(conn, insert_query, params)
    return {"Expense_ID": new_id}