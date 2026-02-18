from fastapi import APIRouter, Request, HTTPException
from loguru import logger

from app.services.auth_service import auth_service
from app.services.twilio_service import twilio_service
from app.services.whatsapp_service import whatsapp_service
from app import database as db

router = APIRouter(prefix="/webhook", tags=["WhatsApp"])


@router.post("/whatsapp")
async def handle_whatsapp_message(request: Request):
    """Receive and process incoming WhatsApp messages from Twilio."""
    form_data = await request.form()
    from_number = form_data.get("From", "")
    message_body = form_data.get("Body", "").strip()
    media_url = form_data.get("MediaUrl0")
    num_media = int(form_data.get("NumMedia", "0"))

    logger.info(f"WhatsApp from {from_number}: {message_body[:100]}")

    try:
        # 1. Authenticate / create customer
        customer = await auth_service.get_or_create_customer(from_number)
        customer_id = customer["id"]

        # 2. Get conversation history for AI context
        history_rows = await db.get_conversation_history(customer_id, limit=10)
        history = [
            {"role": row["role"], "content": row["content"]}
            for row in history_rows
            if row.get("role") in ("user", "assistant")
        ]

        # 3. Resolve media URL
        resolved_media = None
        if media_url or num_media > 0:
            resolved_media = media_url or form_data.get("MediaUrl0")

        # 4. Save user message
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "user",
            "content": message_body or "[image]",
        })

        # 5. Process via WhatsApp service
        response_text = await whatsapp_service.process_message(
            customer_id=customer_id,
            message=message_body,
            media_url=resolved_media,
            history=history,
        )

        # 6. Save bot response
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "assistant",
            "content": response_text,
        })

        # 7. Send reply via Twilio
        await twilio_service.send_message(from_number, response_text)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing WhatsApp message: {e}")
        try:
            await twilio_service.send_message(
                from_number,
                "⚠️ Sorry, something went wrong. Please try again or reply *menu* for options.",
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whatsapp/status")
async def handle_whatsapp_status(request: Request):
    """Handle Twilio delivery receipts / status callbacks."""
    form_data = await request.form()
    message_sid = form_data.get("MessageSid", "")
    message_status = form_data.get("MessageStatus", "")
    logger.info(f"WhatsApp status: SID={message_sid}, Status={message_status}")
    return {"status": "received"}
