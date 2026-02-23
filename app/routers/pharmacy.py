import io
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from loguru import logger

from app import database as db
from app.utils.security import get_current_user
from app.utils.validators import validate_password_strength
from app.services.auth_service import auth_service
from app.services.analytics_service import analytics_service
from app.models.pharmacy import (
    PharmacyLoginRequest,
    ChangePasswordRequest,
    PharmacyProfileUpdate,
)
from app.models.inventory import InventoryCreate, InventoryUpdate
from app.services.stepfun_service import stepfun_service
from pydantic import BaseModel

router = APIRouter(prefix="/api/pharmacy", tags=["Pharmacy Dashboard"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def pharmacy_login(payload: PharmacyLoginRequest):
    """Login with admin-issued credentials."""
    result = await auth_service.pharmacy_login(payload.email, payload.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return result


@router.post("/auth/logout")
async def pharmacy_logout():
    """Logout (client-side token removal)."""
    return {"message": "Logged out successfully"}


@router.get("/auth/me")
async def get_current_pharmacy_user(current_user: dict = Depends(get_current_user)):
    """Get the currently authenticated pharmacy user."""
    safe_user = {k: v for k, v in current_user.items() if k != "password_hash"}
    return {"user": safe_user}


@router.post("/auth/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """Change password (required on first login if must_change_password is set)."""
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")

    validate_password_strength(payload.new_password)

    token = await auth_service.change_pharmacy_password(
        current_user, payload.current_password, payload.new_password
    )
    if not token:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    return {"access_token": token, "token_type": "bearer", "message": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Inventory Management
# ---------------------------------------------------------------------------

@router.get("/inventory")
async def list_inventory(current_user: dict = Depends(get_current_user)):
    """List all inventory for the logged-in pharmacy."""
    items = await db.list_inventory(current_user["pharmacy_id"])
    return {"inventory": items}


@router.post("/inventory")
async def add_inventory(
    payload: InventoryCreate,
    current_user: dict = Depends(get_current_user),
):
    """Add a medicine to inventory. Accepts medicine_id OR free-text medicine_name."""
    medicine_id = payload.medicine_id

    # If no medicine_id provided, find or create by name
    if not medicine_id:
        if not payload.medicine_name or not payload.medicine_name.strip():
            raise HTTPException(status_code=400, detail="Either medicine_id or medicine_name is required")
        name = payload.medicine_name.strip()
        existing = await db.find_medicine_by_name(name)
        if existing:
            medicine_id = existing["id"]
        else:
            med_data = {"name": name}
            if payload.category:
                med_data["category"] = payload.category
            created = await db.create_medicine(med_data)
            medicine_id = created["id"]
            logger.info(f"[INVENTORY] Auto-created medicine '{name}' (id={medicine_id})")

    item = await db.add_inventory_item({
        "pharmacy_id": current_user["pharmacy_id"],
        "medicine_id": medicine_id,
        "price": payload.price,
        "in_stock": payload.in_stock,
        "quantity_available": payload.quantity_available,
    })
    return {"item": item}


@router.put("/inventory/{item_id}")
async def update_inventory(
    item_id: str,
    payload: InventoryUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update a medicine's price, stock status, etc."""
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    item = await db.update_inventory_item(item_id, current_user["pharmacy_id"], update_data)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return {"item": item}


@router.delete("/inventory/{item_id}")
async def delete_inventory(
    item_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a medicine from inventory."""
    await db.delete_inventory_item(item_id, current_user["pharmacy_id"])
    return {"message": "Deleted"}


@router.post("/inventory/bulk-upload")
async def bulk_upload_inventory(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """CSV upload endpoint for bulk inventory management."""
    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {e}")

    required_cols = {"medicine_name", "price"}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {required_cols}. Found: {list(df.columns)}",
        )

    results = {"created": [], "updated": [], "errors": []}
    for _, row in df.iterrows():
        try:
            name = str(row["medicine_name"]).strip()
            if not name:
                continue
            medicine = await db.find_medicine_by_name(name)
            if not medicine:
                med_data = {"name": name}
                if "category" in df.columns and pd.notna(row.get("category")):
                    med_data["category"] = str(row["category"]).strip()
                medicine = await db.create_medicine(med_data)
                results["created"].append(name)
                logger.info(f"[BULK] Auto-created medicine '{name}'")
            in_stock = bool(row["in_stock"]) if "in_stock" in df.columns and pd.notna(row.get("in_stock")) else True
            qty = str(row.get("quantity_available", "In Stock")) if "quantity_available" in df.columns else "In Stock"
            await db.upsert_inventory({
                "pharmacy_id": current_user["pharmacy_id"],
                "medicine_id": medicine["id"],
                "price": float(row["price"]),
                "in_stock": in_stock,
                "quantity_available": qty,
            })
            results["updated"].append(name)
        except Exception as e:
            results["errors"].append(f"{row.get('medicine_name', '?')}: {e}")

    return {"success": results["updated"], "created": results["created"], "errors": results["errors"]}


class FixCsvRequest(BaseModel):
    raw_csv: str


@router.post("/inventory/fix-csv")
async def fix_csv_format(
    payload: FixCsvRequest,
    current_user: dict = Depends(get_current_user),
):
    """Use AI to correct a malformed inventory CSV to the expected format."""
    if len(payload.raw_csv) > 50_000:
        raise HTTPException(status_code=400, detail="CSV too large (max 50 KB)")
    try:
        corrected = stepfun_service.fix_inventory_csv(payload.raw_csv)
        return {"corrected_csv": corrected.strip()}
    except Exception as e:
        logger.error(f"CSV fix failed: {e}")
        raise HTTPException(status_code=502, detail="AI service unavailable. Please fix the CSV manually.")


@router.get("/medicines/search")
async def search_medicine_master(q: str = "", limit: int = 20):
    """Search the medicine master list (for adding to inventory)."""
    medicines = await db.list_medicines(search=q, limit=limit)
    return {"medicines": medicines}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def get_pharmacy_analytics(current_user: dict = Depends(get_current_user)):
    """Dashboard stats: searches, inquiries, popular medicines."""
    stats = await analytics_service.get_pharmacy_stats(current_user["pharmacy_id"])
    return stats


@router.get("/analytics/trending")
async def get_trending_medicines(current_user: dict = Depends(get_current_user)):
    """Most searched medicines this week."""
    trending = await analytics_service.get_trending(current_user["pharmacy_id"])
    return {"trending": trending}


@router.get("/inquiries")
async def list_inquiries(current_user: dict = Depends(get_current_user)):
    """List customer inquiries for this pharmacy."""
    inquiries = await db.list_inquiries(current_user["pharmacy_id"])
    return {"inquiries": inquiries}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
async def get_pharmacy_profile(current_user: dict = Depends(get_current_user)):
    """Get pharmacy details."""
    pharmacy = await db.get_pharmacy_by_id(current_user["pharmacy_id"])
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    return {"pharmacy": pharmacy}


@router.put("/profile")
async def update_pharmacy_profile(
    payload: PharmacyProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update pharmacy info (hours, contact, etc.)."""
    import json as _json
    pharmacy_id = current_user["pharmacy_id"]
    logger.info(f"[PROFILE_UPDATE] pharmacy={pharmacy_id} raw_payload={payload.model_dump()}")

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # opening_hours is JSONB in DB — ensure it's a dict before saving
    if "opening_hours" in update_data:
        oh = update_data["opening_hours"]
        if isinstance(oh, str):
            try:
                parsed = _json.loads(oh)
                if isinstance(parsed, dict):
                    update_data["opening_hours"] = parsed
            except (_json.JSONDecodeError, TypeError):
                # Not valid JSON — remove to avoid JSONB column error
                update_data.pop("opening_hours", None)
                logger.warning(f"[PROFILE_UPDATE] Removed invalid opening_hours string")

    # latitude / longitude — try float first (numeric col), fallback to string (text col)
    for coord_key in ("latitude", "longitude"):
        val = update_data.get(coord_key)
        if val is not None:
            if isinstance(val, str) and val.strip() == "":
                update_data.pop(coord_key)  # empty string → skip
            else:
                try:
                    update_data[coord_key] = float(val)
                except (ValueError, TypeError):
                    update_data.pop(coord_key)

    # Strip empty strings → null for nullable text columns
    for key in ("name", "address", "phone", "suburb", "city", "email",
                "whatsapp_number", "chain_name", "special_services",
                "website", "facebook", "instagram"):
        if key in update_data and update_data[key] == "":
            update_data[key] = None

    logger.info(f"[PROFILE_UPDATE] pharmacy={pharmacy_id} cleaned_data_keys={list(update_data.keys())}")

    try:
        pharmacy = await db.update_pharmacy(pharmacy_id, update_data)
        if not pharmacy:
            raise HTTPException(status_code=404, detail="Pharmacy not found or no changes made")
        return {"pharmacy": pharmacy}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFILE_UPDATE] FAILED pharmacy={pharmacy_id} error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")
