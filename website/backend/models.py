from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class SubscriptionCreate(BaseModel):
    Service_Name: str = Field(min_length=1, max_length=50)
    Provider: str = Field(min_length=1, max_length=50)
    Purpose: Optional[str] = Field(default=None, max_length=250)
    Cost: float = Field(ge=0)
    Billing_Cycle: str = Field(min_length=1, max_length=25)
    Payment_Method: str = Field(min_length=1, max_length=50)
    Start_Date: date
    Is_Active: bool = True


class PaymentMethodCreate(BaseModel):
    Name: str = Field(min_length=1, max_length=50)


class ExpenseCreate(BaseModel):
    Expense_Name: str = Field(min_length=1, max_length=50)
    Provider: str = Field(min_length=1, max_length=50)
    Purpose: Optional[str] = Field(default=None, max_length=250)
    Cost: float = Field(ge=0)
    Payment_Method: str = Field(min_length=1, max_length=50)
    Date: date
    Subscription_ID: Optional[int] = None
