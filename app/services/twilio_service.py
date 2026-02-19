import json
import time
from typing import List, Optional

from twilio.rest import Client
from twilio.request_validator import RequestValidator
from loguru import logger

from app.config import settings


class TwilioService:
    def __init__(self):
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.from_number = settings.TWILIO_WHATSAPP_NUMBER
        self.validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        self._content_cache: dict = {}  # friendly_name -> content_sid

    def _to_wa(self, to: str) -> str:
        return to if to.startswith("whatsapp:") else f"whatsapp:{to}"

    async def send_message(self, to: str, body: str) -> dict:
        """Send a plain text WhatsApp message."""
        to = self._to_wa(to)
        try:
            msg = self.client.messages.create(body=body, from_=self.from_number, to=to)
            logger.info(f"Sent text to {to}, SID: {msg.sid}")
            return {"sid": msg.sid, "status": msg.status}
        except Exception as e:
            logger.error(f"Failed to send text to {to}: {e}")
            raise

    async def send_interactive(self, to: str, content_sid: str, variables: Optional[dict] = None) -> dict:
        """Send an interactive message using a Content Template SID."""
        to = self._to_wa(to)
        try:
            kwargs = {"content_sid": content_sid, "from_": self.from_number, "to": to}
            if variables:
                kwargs["content_variables"] = json.dumps(variables)
            msg = self.client.messages.create(**kwargs)
            logger.info(f"Sent interactive to {to}, SID: {msg.sid}")
            return {"sid": msg.sid, "status": msg.status}
        except Exception as e:
            logger.error(f"Failed to send interactive to {to}: {e}")
            raise

    async def send_location(self, to: str, lat: float, lng: float, label: str, address: str = "") -> dict:
        """Send a location message via persistent_action."""
        to = self._to_wa(to)
        try:
            action = f"geo:{lat},{lng}|{label}"
            msg = self.client.messages.create(
                body=f"📍 {label}\n{address}" if address else f"📍 {label}",
                from_=self.from_number,
                to=to,
                persistent_action=[action],
            )
            logger.info(f"Sent location to {to}, SID: {msg.sid}")
            return {"sid": msg.sid, "status": msg.status}
        except Exception as e:
            logger.error(f"Failed to send location to {to}: {e}")
            raise

    def _get_or_create_content(self, friendly_name: str, types: dict, variables: Optional[dict] = None) -> str:
        """Get cached content SID or create a new content template."""
        if friendly_name in self._content_cache:
            return self._content_cache[friendly_name]
        try:
            # Check if template already exists
            contents = self.client.content.v1.contents.list(limit=100)
            for c in contents:
                if c.friendly_name == friendly_name:
                    self._content_cache[friendly_name] = c.sid
                    return c.sid
        except Exception:
            pass
        try:
            kwargs = {"friendly_name": friendly_name, "types": types}
            if variables:
                kwargs["variables"] = variables
            content = self.client.content.v1.contents.create(**kwargs)
            self._content_cache[friendly_name] = content.sid
            logger.info(f"Created content template '{friendly_name}' -> {content.sid}")
            return content.sid
        except Exception as e:
            logger.error(f"Failed to create content '{friendly_name}': {e}")
            raise

    def get_welcome_template(self) -> str:
        """Get or create the welcome quick-reply template."""
        return self._get_or_create_content(
            "rerun_welcome",
            {"twilio/quick-reply": {
                "body": "💊 *RERUN Health*\nZimbabwe's Medicine Finder\n━━━━━━━━━━━━━━━━━━━━\n\nFind medicines, compare prices, and locate pharmacies across Zimbabwe.\n\nHow can I help you today?",
                "actions": [
                    {"id": "find_medicine", "title": "💊 Find Medicine"},
                    {"id": "near_me", "title": "📍 Near Me"},
                    {"id": "help", "title": "❓ Help"},
                ],
            }},
        )

    def get_menu_template(self) -> str:
        """Get or create the menu quick-reply template."""
        return self._get_or_create_content(
            "rerun_menu",
            {"twilio/quick-reply": {
                "body": "💊 *RERUN Health*\nZimbabwe's Medicine Finder\n━━━━━━━━━━━━━━━━━━━━\n\n*Search Medicine*\nType a medicine name or symptom\n\n*Find Pharmacy*\nType: pharmacy [name or area]\n\n*Scan Prescription*\nSend a photo of your prescription\n━━━━━━━━━━━━━━━━━━━━",
                "actions": [
                    {"id": "find_medicine", "title": "💊 Find Medicine"},
                    {"id": "near_me", "title": "📍 Near Me"},
                    {"id": "scan_rx", "title": "📸 Scan Rx"},
                ],
            }},
        )

    def get_results_nav_template(self) -> str:
        """Get or create the search results navigation template."""
        return self._get_or_create_content(
            "rerun_results_nav",
            {"twilio/quick-reply": {
                "body": "Reply with a *number* for full details, or:",
                "actions": [
                    {"id": "find_medicine", "title": "🔍 New Search"},
                    {"id": "near_me", "title": "📍 Near Me"},
                    {"id": "menu", "title": "📋 Menu"},
                ],
            }},
        )

    def get_pharmacy_actions_template(self) -> str:
        """Get or create the pharmacy detail actions template."""
        return self._get_or_create_content(
            "rerun_pharmacy_actions",
            {"twilio/quick-reply": {
                "body": "What would you like to do?",
                "actions": [
                    {"id": "rate", "title": "⭐ Rate"},
                    {"id": "find_medicine", "title": "🔍 New Search"},
                    {"id": "menu", "title": "📋 Menu"},
                ],
            }},
        )

    async def send_cta(self, to: str, body: str, actions: list) -> dict:
        """Send a call-to-action message with dynamic phone/URL buttons.
        
        actions: list of dicts with keys:
          - title: str (button label, max 20 chars)
          - type: "PHONE_NUMBER" or "URL"
          - phone: str (for PHONE_NUMBER type)
          - url: str (for URL type)
        Max 2 actions per message.
        """
        to = self._to_wa(to)
        # Build a unique name so we don't collide with other pharmacies
        import hashlib
        action_hash = hashlib.md5(json.dumps(actions, sort_keys=True).encode()).hexdigest()[:8]
        friendly_name = f"rerun_cta_{action_hash}"

        cta_actions = []
        for i, a in enumerate(actions[:2]):
            act = {"id": f"cta_{i}", "title": a["title"][:20], "type": a["type"]}
            if a["type"] == "PHONE_NUMBER":
                act["phone"] = a["phone"]
            elif a["type"] == "URL":
                act["url"] = a["url"]
            cta_actions.append(act)

        try:
            content_sid = self._get_or_create_content(
                friendly_name,
                {"twilio/call-to-action": {"body": body, "actions": cta_actions}},
            )
            msg = self.client.messages.create(
                content_sid=content_sid, from_=self.from_number, to=to,
            )
            logger.info(f"Sent CTA to {to}, SID: {msg.sid}")
            return {"sid": msg.sid, "status": msg.status}
        except Exception as e:
            logger.error(f"Failed to send CTA to {to}: {e}")
            raise

    def get_rating_template(self) -> str:
        """Get or create the rating quick-reply template."""
        return self._get_or_create_content(
            "rerun_rating",
            {"twilio/quick-reply": {
                "body": "⭐ How was your experience?\nRate from 1 to 5:",
                "actions": [
                    {"id": "rate_5", "title": "⭐⭐⭐⭐⭐ (5)"},
                    {"id": "rate_4", "title": "⭐⭐⭐⭐ (4)"},
                    {"id": "rate_3", "title": "⭐⭐⭐ (3)"},
                ],
            }},
        )

    def get_post_rating_template(self) -> str:
        """Get or create the post-rating navigation template."""
        return self._get_or_create_content(
            "rerun_post_rating",
            {"twilio/quick-reply": {
                "body": "Thanks for your feedback! What's next?",
                "actions": [
                    {"id": "find_medicine", "title": "🔍 New Search"},
                    {"id": "near_me", "title": "📍 Near Me"},
                    {"id": "menu", "title": "🏠 Main Menu"},
                ],
            }},
        )

    def get_help_template(self) -> str:
        """Get or create the help quick-reply template."""
        return self._get_or_create_content(
            "rerun_help",
            {"twilio/quick-reply": {
                "body": "ℹ️ *RERUN Health — Help*\n━━━━━━━━━━━━━━━━━━━━\n\n💊 *Find Medicine* — Type any medicine name\n📍 *Near Me* — Find pharmacies in your area\n📸 *Scan Rx* — Send a prescription photo\n⭐ *Rate* — Rate a pharmacy after viewing\n\n_Just type what you need!_",
                "actions": [
                    {"id": "find_medicine", "title": "💊 Find Medicine"},
                    {"id": "near_me", "title": "📍 Near Me"},
                    {"id": "menu", "title": "📋 Menu"},
                ],
            }},
        )

    def validate_request(self, url: str, params: dict, signature: str) -> bool:
        """Validate that a request came from Twilio."""
        return self.validator.validate(url, params, signature)


twilio_service = TwilioService()
