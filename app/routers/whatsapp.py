from fastapi import APIRouter, Request, HTTPException
from loguru import logger

from app.services.auth_service import auth_service
from app.services.twilio_service import twilio_service
from app.services.whatsapp_service import whatsapp_service
from app import database as db

router = APIRouter(prefix="/webhook", tags=["WhatsApp"])


async def _send_action(to: str, action: dict) -> None:
    """Dispatch a single message action via Twilio. Only text and location supported."""
    action_type = action.get("type", "text")

    if action_type == "text":
        await twilio_service.send_message(to, action["body"])

    elif action_type == "location":
        try:
            await twilio_service.send_location(
                to, action["lat"], action["lng"], action["label"], action.get("address", "")
            )
        except Exception as e:
            logger.warning(f"Location send failed, falling back to text: {e}")
            lat, lng = action.get("lat", ""), action.get("lng", "")
            maps_url = f"https://maps.google.com/?q={lat},{lng}" if lat and lng else ""
            await twilio_service.send_message(to, f"📍 {action['label']}\n{action.get('address', '')}\n{maps_url}")

    else:
        logger.warning(f"Unknown action type '{action_type}', skipping")


@router.post("/whatsapp")
async def handle_whatsapp_message(request: Request):
    """Receive and process incoming WhatsApp messages from Twilio."""
    form_data = await request.form()
    from_number = form_data.get("From", "")
    message_body = form_data.get("Body", "").strip()
    media_url = form_data.get("MediaUrl0")
    num_media = int(form_data.get("NumMedia", "0"))

    # Twilio sends Latitude/Longitude when user shares a location pin
    twilio_lat = form_data.get("Latitude")
    twilio_lng = form_data.get("Longitude")

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

        # 4. If Twilio sent native location, inject coordinates into message
        if twilio_lat and twilio_lng:
            message_body = f"{twilio_lat},{twilio_lng}"

        # 5. Save user message
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "user",
            "content": message_body or "[image]",
        })

        # 6. Process via WhatsApp service — returns list of message actions
        actions = await whatsapp_service.process_message(
            customer_id=customer_id,
            message=message_body,
            media_url=resolved_media,
            history=history,
        )

        # 6. Build a text summary for conversation storage
        text_parts = [a["body"] for a in actions if a.get("type") == "text"]
        response_summary = "\n\n".join(text_parts) if text_parts else "[interactive message]"
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "assistant",
            "content": response_summary,
        })

        # 7. Send each action via Twilio
        for action in actions:
            await _send_action(from_number, action)

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
