from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MedicineBase(BaseModel):
    name: str
    generic_name: Optional[str] = None
    category: Optional[str] = None
    dosage_form: Optional[str] = None
    strength: Optional[str] = None
    description: Optional[str] = None
    requires_prescription: bool = False


class MedicineCreate(MedicineBase):
    pass


class MedicineResponse(MedicineBase):
    id: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MedicineSearchRequest(BaseModel):
    search_query: str
    customer_phone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class MedicineWithPharmacies(MedicineResponse):
    pharmacies: List[dict] = []
