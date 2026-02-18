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
    """Add a new medicine to inventory."""
    item = await db.add_inventory_item({
        "pharmacy_id": current_user["pharmacy_id"],
        "medicine_id": payload.medicine_id,
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

    required_cols = {"medicine_name", "price", "in_stock"}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {required_cols}. Found: {list(df.columns)}",
        )

    results = {"success": [], "errors": []}
    for _, row in df.iterrows():
        medicine = await db.find_medicine_by_name(row["medicine_name"])
        if not medicine:
            results["errors"].append(f"Not found: {row['medicine_name']}")
            continue
        await db.upsert_inventory({
            "pharmacy_id": current_user["pharmacy_id"],
            "medicine_id": medicine["id"],
            "price": float(row["price"]),
            "in_stock": bool(row["in_stock"]),
            "quantity_available": str(row.get("quantity_available", "In Stock")),
        })
        results["success"].append(medicine["name"])

    return results


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
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    # opening_hours is JSONB in DB — parse JSON string to dict if needed
    if "opening_hours" in update_data and isinstance(update_data["opening_hours"], str):
        try:
            update_data["opening_hours"] = _json.loads(update_data["opening_hours"])
        except (_json.JSONDecodeError, TypeError):
            pass  # keep as-is if not valid JSON
    pharmacy = await db.update_pharmacy(current_user["pharmacy_id"], update_data)
    return {"pharmacy": pharmacy}
