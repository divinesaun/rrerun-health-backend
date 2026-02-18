from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str = "admin"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
