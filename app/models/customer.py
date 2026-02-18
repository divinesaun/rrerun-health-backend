from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CustomerBase(BaseModel):
    phone: str
    name: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerResponse(CustomerBase):
    id: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerAuthRequest(BaseModel):
    phone: str


class CustomerInquiryRequest(BaseModel):
    pharmacy_id: str
    medicine_id: str
    message: Optional[str] = None
