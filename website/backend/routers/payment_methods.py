import pyodbc
from fastapi import APIRouter, HTTPException
from database import get_connection, run_query, run_insert
from models import PaymentMethodCreate

router = APIRouter()


@router.get("/api/payment-methods")
def get_payment_methods():
    with get_connection() as conn:
        rows = run_query(conn, "SELECT Payment_Method_ID, [Name] FROM PaymentMethods ORDER BY [Name];")
    return {"paymentMethods": rows}


@router.post("/api/payment-methods", status_code=201)
def create_payment_method(method: PaymentMethodCreate):
    insert_query = """
        INSERT INTO PaymentMethods ([Name])
        OUTPUT INSERTED.Payment_Method_ID
        VALUES (?);
    """
    with get_connection() as conn:
        try:
            new_id = run_insert(conn, insert_query, (method.Name,))
        except pyodbc.IntegrityError:
            raise HTTPException(status_code=409, detail="Payment method already exists")
    return {"Payment_Method_ID": new_id, "Name": method.Name}
