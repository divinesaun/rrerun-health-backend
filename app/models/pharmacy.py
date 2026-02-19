from pydantic import BaseModel, EmailStr
from typing import Optional, Union
from datetime import datetime


class PharmacyBase(BaseModel):
    name: str
    address: str
    suburb: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    opening_hours: Optional[Union[str, dict]] = None


class CreatePharmacyRequest(PharmacyBase):
    email: str  # required — used to create the pharmacy user account
    contact_name: str


class UpdatePharmacyRequest(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    suburb: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    opening_hours: Optional[Union[str, dict]] = None
    verified: Optional[bool] = None


class PharmacyResponse(PharmacyBase):
    id: str
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PharmacyUserBase(BaseModel):
    email: str
    name: Optional[str] = None
    role: str = "manager"


class PharmacyUserResponse(PharmacyUserBase):
    id: str
    pharmacy_id: str
    must_change_password: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreatePharmacyUserRequest(BaseModel):
    email: str
    name: Optional[str] = None
    pharmacy_id: str
    role: str = "staff"


class PharmacyLoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str


class PharmacyProfileUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    suburb: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    opening_hours: Optional[Union[str, dict]] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    accepts_medical_aid: Optional[bool] = None
    has_delivery: Optional[bool] = None
    is_24_hours: Optional[bool] = None
    parking_available: Optional[bool] = None
    special_services: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    chain_name: Optional[str] = None
