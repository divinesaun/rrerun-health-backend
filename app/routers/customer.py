from fastapi import APIRouter, HTTPException

from app.services.auth_service import auth_service
from app import database as db
from app.models.customer import CustomerAuthRequest, CustomerInquiryRequest

router = APIRouter(prefix="/api/customers", tags=["Customers"])


@router.post("/auth")
async def customer_auth(payload: CustomerAuthRequest):
    """Auto-create or login a customer by phone number."""
    customer = await auth_service.get_or_create_customer(payload.phone)
    return {"customer": customer}


@router.get("/me")
async def get_customer_profile(phone: str):
    """Get current customer profile by phone number."""
    customer = await db.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"customer": customer}


@router.get("/me/history")
async def get_customer_history(phone: str, limit: int = 50):
    """Get search history for a customer."""
    customer = await db.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    history = await db.get_customer_search_history(customer["id"], limit)
    return {"history": history}


@router.post("/inquiry")
async def log_customer_inquiry(payload: CustomerInquiryRequest, phone: str):
    """Log when a customer contacts / selects a pharmacy."""
    customer = await db.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    inquiry = await db.create_inquiry({
        "customer_id": customer["id"],
        "pharmacy_id": payload.pharmacy_id,
        "medicine_id": payload.medicine_id,
        "message": payload.message,
    })
    return {"inquiry": inquiry}
