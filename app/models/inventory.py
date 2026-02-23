from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class InventoryBase(BaseModel):
    medicine_id: Optional[str] = None
    price: float
    in_stock: bool = True
    quantity_available: Optional[str] = "In Stock"


class InventoryCreate(InventoryBase):
    medicine_name: Optional[str] = None  # free-text name if medicine_id is not provided
    category: Optional[str] = None


class InventoryUpdate(BaseModel):
    price: Optional[float] = None
    in_stock: Optional[bool] = None
    quantity_available: Optional[str] = None


class InventoryResponse(InventoryBase):
    id: str
    pharmacy_id: str
    times_searched: int = 0
    last_search_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    medicines: Optional[dict] = None

    class Config:
        from_attributes = True
