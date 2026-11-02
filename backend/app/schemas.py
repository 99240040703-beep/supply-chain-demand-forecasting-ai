from pydantic import BaseModel, Field, EmailStr

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
class LoginIn(BaseModel):
    email: EmailStr
    password: str
class SupplierIn(BaseModel):
    supplier_id: str
    name: str
    email: EmailStr | None = None
    lead_time: int = Field(default=7, ge=1, le=365)
    reliability: float = Field(default=0.95, ge=0, le=1)
class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
class ForecastIn(BaseModel):
    days: int = Field(default=30, ge=7, le=90)
    product_id: str | None = None

from typing import Literal

class PurchaseOrderIn(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=1000000)
    supplier_id: str | None = None

class PurchaseOrderStatusIn(BaseModel):
    status: Literal["SUBMITTED", "APPROVED", "RECEIVED", "CANCELLED"]
