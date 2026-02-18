from typing import Dict

from loguru import logger

from app import database as db
from app.utils.helpers import generate_temp_password
from app.utils.security import hash_password
from app.services.email_service import email_service
from app.config import settings


class AdminService:
    async def create_pharmacy_with_user(self, payload: Dict) -> Dict:
        """Create a new pharmacy and its initial user account, then email credentials."""
        pharmacy = await db.create_pharmacy({
            "name": payload["name"],
            "address": payload["address"],
            "suburb": payload.get("suburb"),
            "phone": payload.get("phone"),
            "email": payload.get("email"),
            "whatsapp_number": payload.get("whatsapp_number"),
            "opening_hours": payload.get("opening_hours"),
            "verified": True,
        })

        temp_password = generate_temp_password()
        hashed = hash_password(temp_password)

        user = await db.create_pharmacy_user({
            "email": payload["email"],
            "password_hash": hashed,
            "pharmacy_id": pharmacy["id"],
            "name": payload.get("contact_name", ""),
            "role": "manager",
            "must_change_password": True,
        })

        email_sent = False
        try:
            await email_service.send_pharmacy_welcome(
                to_email=payload["email"],
                pharmacy_name=payload["name"],
                contact_name=payload.get("contact_name", ""),
                temp_password=temp_password,
                login_url=f"{settings.DASHBOARD_URL}/login",
            )
            email_sent = True
        except Exception as e:
            logger.error(f"Failed to send welcome email to {payload['email']}: {e}")

        result = {
            "pharmacy": pharmacy,
            "user": {k: v for k, v in user.items() if k != "password_hash"},
            "email_sent": email_sent,
        }
        # Include temp password in dev mode so it can be used without email
        if settings.ENVIRONMENT == "development":
            result["temp_password"] = temp_password
        return result

    async def create_pharmacy_user(self, payload: Dict) -> Dict:
        """Create an additional pharmacy user account and email credentials."""
        pharmacy = await db.get_pharmacy_by_id(payload["pharmacy_id"])
        if not pharmacy:
            return {"error": "Pharmacy not found"}

        temp_password = generate_temp_password()
        hashed = hash_password(temp_password)

        user = await db.create_pharmacy_user({
            "email": payload["email"],
            "password_hash": hashed,
            "pharmacy_id": payload["pharmacy_id"],
            "name": payload.get("name", ""),
            "role": payload.get("role", "staff"),
            "must_change_password": True,
        })

        email_sent = False
        try:
            await email_service.send_pharmacy_welcome(
                to_email=payload["email"],
                pharmacy_name=pharmacy["name"],
                contact_name=payload.get("name", ""),
                temp_password=temp_password,
                login_url=f"{settings.DASHBOARD_URL}/login",
            )
            email_sent = True
        except Exception as e:
            logger.error(f"Failed to send welcome email to {payload['email']}: {e}")

        result = {
            "user": {k: v for k, v in user.items() if k != "password_hash"},
            "email_sent": email_sent,
        }
        if settings.ENVIRONMENT == "development":
            result["temp_password"] = temp_password
        return result

    async def resend_credentials(self, pharmacy_id: str) -> Dict:
        """Generate a new temp password for the pharmacy's user and email it."""
        pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
        if not pharmacy:
            return {"error": "Pharmacy not found"}

        users = await db.list_pharmacy_users(pharmacy_id)
        if not users:
            return {"error": "No users found for this pharmacy"}

        user = users[0]
        temp_password = generate_temp_password()
        hashed = hash_password(temp_password)

        await db.update_pharmacy_user(user["id"], {
            "password_hash": hashed,
            "must_change_password": True,
        })

        email_sent = False
        try:
            await email_service.send_pharmacy_welcome(
                to_email=user["email"],
                pharmacy_name=pharmacy["name"],
                contact_name=user.get("name", ""),
                temp_password=temp_password,
            )
            email_sent = True
        except Exception as e:
            logger.error(f"Failed to resend credentials to {user['email']}: {e}")

        return {"email_sent": email_sent, "user_email": user["email"]}

    async def reset_user_password(self, user_id: str) -> Dict:
        """Admin-triggered password reset for a pharmacy user."""
        user = await db.get_pharmacy_user_by_id(user_id)
        if not user:
            return {"error": "User not found"}

        temp_password = generate_temp_password()
        hashed = hash_password(temp_password)

        await db.update_pharmacy_user(user_id, {
            "password_hash": hashed,
            "must_change_password": True,
        })

        email_sent = False
        try:
            await email_service.send_password_reset(
                to_email=user["email"],
                contact_name=user.get("name", ""),
                temp_password=temp_password,
            )
            email_sent = True
        except Exception as e:
            logger.error(f"Failed to send reset email to {user['email']}: {e}")

        return {"email_sent": email_sent}


admin_service = AdminService()
