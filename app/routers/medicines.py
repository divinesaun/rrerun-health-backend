from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app import database as db
from app.utils.security import require_admin
from app.services.search_service import search_service
from app.services.stepfun_service import stepfun_service
from app.services.analytics_service import analytics_service
from app.models.medicine import MedicineSearchRequest, MedicineCreate
from app.utils.helpers import sort_pharmacies_by_distance

router = APIRouter(prefix="/api", tags=["Medicines & Search"])


# ---------------------------------------------------------------------------
# Main Search Endpoint
# ---------------------------------------------------------------------------

@router.post("/search")
async def search_medicines(payload: MedicineSearchRequest):
    """Main search endpoint (used by WhatsApp bot and API clients)."""
    # Use StepFun to extract medicine names from the query
    medicine_names = stepfun_service.extract_medicines_from_text(payload.search_query)

    if not medicine_names:
        return {"medicines": [], "message": "No medicines identified from your query"}

    results = await search_service.find_medicines(
        medicine_names,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )

    # Log the search
    customer = None
    customer_id = None
    if payload.customer_phone:
        customer = await db.get_customer_by_phone(payload.customer_phone)
        customer_id = customer["id"] if customer else None

    await analytics_service.log_search(customer_id, payload.search_query, results)

    return {"medicines": results, "query": payload.search_query, "extracted_names": medicine_names}


# ---------------------------------------------------------------------------
# Medicine CRUD
# ---------------------------------------------------------------------------

@router.get("/medicines")
async def list_medicines(search: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List all medicines with optional search filter."""
    medicines = await db.list_medicines(search=search, limit=limit, offset=offset)
    return {"medicines": medicines}


@router.get("/medicines/{medicine_id}")
async def get_medicine(medicine_id: str):
    """Get medicine details."""
    medicine = await db.get_medicine_by_id(medicine_id)
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return {"medicine": medicine}


@router.post("/medicines")
async def create_medicine(
    payload: MedicineCreate,
    admin: dict = Depends(require_admin),
):
    """Create a new medicine in the master database (admin only)."""
    medicine = await db.create_medicine(payload.model_dump())
    return {"medicine": medicine}


@router.put("/medicines/{medicine_id}")
async def update_medicine(
    medicine_id: str,
    payload: MedicineCreate,
    admin: dict = Depends(require_admin),
):
    """Update a medicine in the master database (admin only)."""
    existing = await db.get_medicine_by_id(medicine_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Medicine not found")
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    medicine = await db.update_medicine(medicine_id, update_data)
    return {"medicine": medicine}


@router.delete("/medicines/{medicine_id}")
async def delete_medicine(
    medicine_id: str,
    admin: dict = Depends(require_admin),
):
    """Delete a medicine from the master database (admin only)."""
    existing = await db.get_medicine_by_id(medicine_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Medicine not found")
    await db.delete_medicine(medicine_id)
    return {"message": "Medicine deleted"}


@router.get("/medicines/{medicine_id}/alternatives")
async def get_alternatives(medicine_id: str):
    """Get cheaper/generic alternatives for a medicine."""
    alternatives = await db.get_medicine_alternatives(medicine_id)
    return {"alternatives": alternatives}


@router.get("/medicines/{medicine_id}/availability")
async def get_availability(medicine_id: str):
    """Check which pharmacies have this medicine in stock."""
    availability = await db.get_medicine_availability(medicine_id)
    return {"availability": availability}


# ---------------------------------------------------------------------------
# Pharmacy Discovery
# ---------------------------------------------------------------------------

@router.get("/pharmacies")
async def list_pharmacies(suburb: Optional[str] = None):
    """List all active pharmacies with optional suburb filter."""
    pharmacies = await db.list_pharmacies(active_only=True)
    if suburb:
        pharmacies = [p for p in pharmacies if (p.get("suburb") or "").lower() == suburb.lower()]
    return {"pharmacies": pharmacies}


@router.get("/pharmacies/{pharmacy_id}")
async def get_pharmacy(pharmacy_id: str):
    """Get pharmacy details."""
    pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    return {"pharmacy": pharmacy}


@router.get("/pharmacies/nearby")
async def find_nearby_pharmacies(latitude: float, longitude: float, radius_km: float = 10.0):
    """Find pharmacies near a location (lat/long)."""
    pharmacies = await db.list_pharmacies(active_only=True)
    sorted_pharmacies = sort_pharmacies_by_distance(pharmacies, latitude, longitude)
    nearby = [p for p in sorted_pharmacies if p.get("distance_km") is not None and p["distance_km"] <= radius_km]
    return {"pharmacies": nearby}
