from fastapi import APIRouter, Depends, HTTPException

from app import database as db
from app.utils.security import require_admin
from app.services.auth_service import auth_service
from app.services.admin_service import admin_service
from app.models.admin import AdminLoginRequest
from app.models.pharmacy import CreatePharmacyRequest, UpdatePharmacyRequest, CreatePharmacyUserRequest

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# Admin Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def admin_login(payload: AdminLoginRequest):
    """Admin login (email/password -> JWT with role: admin)."""
    result = await auth_service.admin_login(payload.email, payload.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return result


@router.get("/auth/me")
async def get_admin_profile(admin: dict = Depends(require_admin)):
    """Get current admin profile."""
    safe_admin = {k: v for k, v in admin.items() if k != "password_hash"}
    return {"user": safe_admin}


# ---------------------------------------------------------------------------
# Pharmacy Management
# ---------------------------------------------------------------------------

@router.get("/pharmacies")
async def list_pharmacies(admin: dict = Depends(require_admin)):
    """List all pharmacies (with status)."""
    pharmacies = await db.list_pharmacies(active_only=False)
    for p in pharmacies:
        users = await db.list_pharmacy_users(p["id"])
        p["user_count"] = len(users)
    return {"pharmacies": pharmacies}


@router.post("/pharmacies")
async def create_pharmacy(
    payload: CreatePharmacyRequest,
    admin: dict = Depends(require_admin),
):
    """Create a new pharmacy and its initial user account."""
    result = await admin_service.create_pharmacy_with_user(payload.model_dump())
    return result


@router.put("/pharmacies/{pharmacy_id}")
async def update_pharmacy(
    pharmacy_id: str,
    payload: UpdatePharmacyRequest,
    admin: dict = Depends(require_admin),
):
    """Edit pharmacy details."""
    import json as _json
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    # opening_hours is JSONB in DB — ensure it's a dict before saving
    if "opening_hours" in update_data:
        oh = update_data["opening_hours"]
        if isinstance(oh, str):
            try:
                update_data["opening_hours"] = _json.loads(oh)
            except (_json.JSONDecodeError, TypeError):
                pass
    pharmacy = await db.update_pharmacy(pharmacy_id, update_data)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    return {"pharmacy": pharmacy}


@router.delete("/pharmacies/{pharmacy_id}")
async def delete_pharmacy(
    pharmacy_id: str,
    admin: dict = Depends(require_admin),
):
    """Delete a pharmacy and all related records (users, inventory, inquiries)."""
    existing = await db.get_pharmacy_by_id(pharmacy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    await db.delete_pharmacy(pharmacy_id)
    return {"message": "Pharmacy deleted"}


@router.get("/pharmacies/{pharmacy_id}/users")
async def list_pharmacy_users(
    pharmacy_id: str,
    admin: dict = Depends(require_admin),
):
    """List users for a specific pharmacy."""
    users = await db.list_pharmacy_users(pharmacy_id)
    safe_users = [{k: v for k, v in u.items() if k != "password_hash"} for u in users]
    return {"users": safe_users}


@router.post("/pharmacies/{pharmacy_id}/resend-credentials")
async def resend_credentials(
    pharmacy_id: str,
    admin: dict = Depends(require_admin),
):
    """Resend login credentials email to pharmacy."""
    result = await admin_service.resend_credentials(pharmacy_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_all_users(admin: dict = Depends(require_admin)):
    """List all pharmacy users across all pharmacies."""
    users = await db.list_pharmacy_users()
    safe_users = []
    for u in users:
        row = {k: v for k, v in u.items() if k not in ("password_hash", "pharmacies")}
        # Flatten Supabase join: pharmacies: {name: "X"} → pharmacy_name: "X"
        pharmacies_join = u.get("pharmacies")
        if isinstance(pharmacies_join, dict):
            row["pharmacy_name"] = pharmacies_join.get("name", "")
        else:
            row["pharmacy_name"] = ""
        safe_users.append(row)
    return {"users": safe_users}


@router.post("/users")
async def create_pharmacy_user(
    payload: CreatePharmacyUserRequest,
    admin: dict = Depends(require_admin),
):
    """Create a pharmacy user with auto-generated temp password and email credentials."""
    result = await admin_service.create_pharmacy_user(payload.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    """Remove a pharmacy user AND its linked pharmacy (bidirectional cascade)."""
    user = await db.get_pharmacy_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    pharmacy_id = user.get("pharmacy_id")
    if pharmacy_id:
        await db.delete_pharmacy(pharmacy_id)
    else:
        await db.delete_pharmacy_user(user_id)
    return {"message": "User and associated pharmacy deleted"}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def admin_analytics(admin: dict = Depends(require_admin)):
    """Platform-wide analytics for the admin dashboard."""
    overview = await db.get_admin_overview_stats()
    trending = await db.get_admin_trending_medicines()
    return {
        "overview": overview,
        "trending_medicines": trending,
        "recent_inquiries": [],
    }


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    """Admin-triggered password reset — generates new temp password and emails it."""
    result = await admin_service.reset_user_password(user_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# System Settings (read-only view of env config)
# ---------------------------------------------------------------------------

@router.get("/settings")
async def get_settings(admin: dict = Depends(require_admin)):
    """Return current system settings (masked secrets)."""
    from app.config import settings as cfg

    def mask(val: str) -> str:
        if not val or len(val) < 6:
            return "****"
        return val[:3] + "*" * (len(val) - 6) + val[-3:]

    return {
        "settings": {
            "jwt": {
                "algorithm": cfg.JWT_ALGORITHM,
                "expiry_minutes": cfg.JWT_EXPIRE_MINUTES,
            },
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": cfg.GMAIL_ADDRESS,
                "from_email": cfg.GMAIL_ADDRESS,
            },
            "twilio": {
                "account_sid": mask(cfg.TWILIO_ACCOUNT_SID),
                "whatsapp_from": cfg.TWILIO_WHATSAPP_NUMBER,
            },
            "ocr": {
                "provider": "ocrspace",
                "api_key": mask(cfg.OCRSPACE_API_KEY),
            },
            "openrouter": {
                "api_key": mask(cfg.OPENROUTER_API_KEY),
                "model": cfg.STEPFUN_MODEL,
            },
        }
    }


@router.put("/settings")
async def update_settings(
    payload: dict,
    admin: dict = Depends(require_admin),
):
    """Update system settings. In production these should persist to a DB or vault.
    For now this is a placeholder that acknowledges the request."""
    # In a real deployment, you'd write to a settings table or .env management
    return {"settings": payload, "message": "Settings received (runtime-only; restart will reset)"}
