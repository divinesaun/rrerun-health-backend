import re
from fastapi import HTTPException


def validate_phone(phone: str) -> str:
    """Normalize and validate a phone number. Strips 'whatsapp:' prefix if present."""
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    phone = re.sub(r"[^\d+]", "", phone)
    if not re.match(r"^\+?\d{7,15}$", phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format")
    return phone


def validate_password_strength(password: str) -> None:
    """Enforce minimum password strength: >=8 chars, at least 1 digit."""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")


def validate_email(email: str) -> str:
    """Basic email format validation."""
    email = email.strip().lower()
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return email
