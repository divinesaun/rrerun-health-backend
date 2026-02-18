from fastapi import APIRouter, Body

from app.services.twilio_service import twilio_service

router = APIRouter(prefix="/api", tags=["General"])


@router.post("/whatsapp/send")
async def send_whatsapp_message(
    to: str = Body(...),
    body: str = Body(...),
):
    """Send an outbound WhatsApp message (proactive notifications)."""
    result = await twilio_service.send_message(to, body)
    return {"message": "Sent", "details": result}
