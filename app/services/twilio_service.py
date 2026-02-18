from twilio.rest import Client
from twilio.request_validator import RequestValidator
from loguru import logger

from app.config import settings


class TwilioService:
    def __init__(self):
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.from_number = settings.TWILIO_WHATSAPP_NUMBER
        self.validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)

    async def send_message(self, to: str, body: str) -> dict:
        """Send a WhatsApp message via Twilio."""
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"
        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to,
            )
            logger.info(f"Sent WhatsApp message to {to}, SID: {message.sid}")
            return {"sid": message.sid, "status": message.status}
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {to}: {e}")
            raise

    def validate_request(self, url: str, params: dict, signature: str) -> bool:
        """Validate that a request came from Twilio."""
        return self.validator.validate(url, params, signature)


twilio_service = TwilioService()
