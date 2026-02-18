from typing import Optional, Dict

from loguru import logger

from app import database as db
from app.utils.security import hash_password, verify_password, create_access_token
from app.utils.validators import validate_phone


class AuthService:
    async def get_or_create_customer(self, phone_raw: str) -> Dict:
        """Auto-create or retrieve a customer by phone (WhatsApp auth)."""
        phone = validate_phone(phone_raw)
        customer = await db.get_customer_by_phone(phone)
        if not customer:
            customer = await db.create_customer({"phone": phone})
            logger.info(f"Created new customer: {phone}")
        return customer

    async def pharmacy_login(self, email: str, password: str) -> Dict:
        """Authenticate a pharmacy user and return JWT + user info."""
        user = await db.get_pharmacy_user_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            return None
        token = create_access_token({
            "sub": str(user["id"]),
            "pharmacy_id": str(user["pharmacy_id"]),
            "role": "pharmacy",
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "must_change_password": user.get("must_change_password", False),
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name"),
                "pharmacy_id": user["pharmacy_id"],
                "role": user.get("role", "manager"),
            },
        }

    async def admin_login(self, email: str, password: str) -> Optional[Dict]:
        """Authenticate the admin user and return JWT."""
        admin = await db.get_admin_by_email(email)
        if not admin or not verify_password(password, admin["password_hash"]):
            return None
        token = create_access_token({
            "sub": admin["email"],
            "role": "admin",
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": admin["id"],
                "email": admin["email"],
                "name": admin.get("name"),
                "role": "admin",
            },
        }

    async def change_pharmacy_password(
        self, user: Dict, current_password: str, new_password: str
    ) -> str:
        """Change a pharmacy user's password. Returns a fresh JWT."""
        if not verify_password(current_password, user["password_hash"]):
            return None
        new_hash = hash_password(new_password)
        await db.update_pharmacy_user(user["id"], {
            "password_hash": new_hash,
            "must_change_password": False,
        })
        token = create_access_token({
            "sub": str(user["id"]),
            "pharmacy_id": str(user["pharmacy_id"]),
            "role": "pharmacy",
        })
        return token


auth_service = AuthService()
