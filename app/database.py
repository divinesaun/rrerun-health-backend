from supabase import create_client, Client
from app.config import settings
from loguru import logger
from typing import Optional, List, Dict, Any

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

async def get_admin_by_email(email: str) -> Optional[Dict]:
    result = supabase.table("admins").select("*").eq("email", email).execute()
    return result.data[0] if result.data else None


async def create_admin(data: Dict) -> Dict:
    result = supabase.table("admins").insert(data).execute()
    return result.data[0]


# ---------------------------------------------------------------------------
# Customer helpers
# ---------------------------------------------------------------------------

async def get_customer_by_phone(phone: str) -> Optional[Dict]:
    result = supabase.table("customers").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


async def create_customer(data: Dict) -> Dict:
    result = supabase.table("customers").insert(data).execute()
    return result.data[0]


async def get_customer_by_id(customer_id: str) -> Optional[Dict]:
    result = supabase.table("customers").select("*").eq("id", customer_id).execute()
    return result.data[0] if result.data else None


async def get_customer_search_history(customer_id: str, limit: int = 50) -> List[Dict]:
    result = (
        supabase.table("search_logs")
        .select("*")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Pharmacy helpers
# ---------------------------------------------------------------------------

async def create_pharmacy(data: Dict) -> Dict:
    result = supabase.table("pharmacies").insert(data).execute()
    return result.data[0]


async def get_pharmacy_by_id(pharmacy_id: str) -> Optional[Dict]:
    result = supabase.table("pharmacies").select("*").eq("id", pharmacy_id).execute()
    return result.data[0] if result.data else None


async def list_pharmacies(active_only: bool = True) -> List[Dict]:
    query = supabase.table("pharmacies").select("*")
    if active_only:
        query = query.eq("is_active", True)
    result = query.order("name").execute()
    return result.data


async def update_pharmacy(pharmacy_id: str, data: Dict) -> Optional[Dict]:
    result = supabase.table("pharmacies").update(data).eq("id", pharmacy_id).execute()
    return result.data[0] if result.data else None


async def deactivate_pharmacy(pharmacy_id: str) -> Optional[Dict]:
    return await update_pharmacy(pharmacy_id, {"is_active": False})


async def delete_pharmacy(pharmacy_id: str) -> bool:
    """Hard-delete a pharmacy. CASCADE FKs remove related users, inventory, inquiries."""
    result = supabase.table("pharmacies").delete().eq("id", pharmacy_id).execute()
    return bool(result.data)


# ---------------------------------------------------------------------------
# Pharmacy user helpers
# ---------------------------------------------------------------------------

async def create_pharmacy_user(data: Dict) -> Dict:
    result = supabase.table("pharmacy_users").insert(data).execute()
    return result.data[0]


async def get_pharmacy_user_by_email(email: str) -> Optional[Dict]:
    result = supabase.table("pharmacy_users").select("*").eq("email", email).execute()
    return result.data[0] if result.data else None


async def get_pharmacy_user_by_id(user_id: str) -> Optional[Dict]:
    result = supabase.table("pharmacy_users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None


async def update_pharmacy_user(user_id: str, data: Dict) -> Dict:
    result = supabase.table("pharmacy_users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


async def delete_pharmacy_user(user_id: str) -> None:
    supabase.table("pharmacy_users").delete().eq("id", user_id).execute()


async def list_pharmacy_users(pharmacy_id: Optional[str] = None) -> List[Dict]:
    query = supabase.table("pharmacy_users").select("*, pharmacies(name)")
    if pharmacy_id:
        query = query.eq("pharmacy_id", pharmacy_id)
    result = query.order("created_at", desc=True).execute()
    return result.data


# ---------------------------------------------------------------------------
# Medicine helpers
# ---------------------------------------------------------------------------

async def list_medicines(search: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict]:
    query = supabase.table("medicines").select("*")
    if search:
        query = query.ilike("name", f"%{search}%")
    result = query.order("name").range(offset, offset + limit - 1).execute()
    return result.data


async def get_medicine_by_id(medicine_id: str) -> Optional[Dict]:
    result = supabase.table("medicines").select("*").eq("id", medicine_id).execute()
    return result.data[0] if result.data else None


async def find_medicine_by_name(name: str) -> Optional[Dict]:
    result = supabase.table("medicines").select("*").ilike("name", f"%{name}%").limit(1).execute()
    return result.data[0] if result.data else None


async def create_medicine(data: Dict) -> Dict:
    result = supabase.table("medicines").insert(data).execute()
    return result.data[0]


async def update_medicine(medicine_id: str, data: Dict) -> Dict:
    result = supabase.table("medicines").update(data).eq("id", medicine_id).execute()
    return result.data[0] if result.data else {}


async def delete_medicine(medicine_id: str) -> None:
    supabase.table("medicines").delete().eq("id", medicine_id).execute()


async def get_medicine_alternatives(medicine_id: str) -> List[Dict]:
    medicine = await get_medicine_by_id(medicine_id)
    if not medicine or not medicine.get("category"):
        return []
    result = (
        supabase.table("medicines")
        .select("*")
        .eq("category", medicine["category"])
        .neq("id", medicine_id)
        .order("name")
        .limit(10)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------

async def list_inventory(pharmacy_id: str) -> List[Dict]:
    result = (
        supabase.table("inventory")
        .select("*, medicines(name, category, dosage_forms)")
        .eq("pharmacy_id", pharmacy_id)
        .order("last_updated", desc=True)
        .execute()
    )
    return result.data


async def add_inventory_item(data: Dict) -> Dict:
    result = supabase.table("inventory").insert(data).execute()
    return result.data[0]


async def update_inventory_item(item_id: str, pharmacy_id: str, data: Dict) -> Dict:
    result = (
        supabase.table("inventory")
        .update(data)
        .eq("id", item_id)
        .eq("pharmacy_id", pharmacy_id)
        .execute()
    )
    return result.data[0] if result.data else {}


async def delete_inventory_item(item_id: str, pharmacy_id: str) -> None:
    supabase.table("inventory").delete().eq("id", item_id).eq("pharmacy_id", pharmacy_id).execute()


async def upsert_inventory(data: Dict) -> Dict:
    existing = (
        supabase.table("inventory")
        .select("id")
        .eq("pharmacy_id", data["pharmacy_id"])
        .eq("medicine_id", data["medicine_id"])
        .execute()
    )
    if existing.data:
        result = (
            supabase.table("inventory")
            .update(data)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        result = supabase.table("inventory").insert(data).execute()
    return result.data[0] if result.data else {}


async def get_inventory_item(item_id: str) -> Optional[Dict]:
    result = supabase.table("inventory").select("*").eq("id", item_id).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

async def search_medicines_with_inventory(medicine_names: List[str]) -> List[Dict]:
    """Search for medicines by name and include pharmacy inventory info."""
    results = []
    for name in medicine_names:
        medicines = (
            supabase.table("medicines")
            .select("*")
            .ilike("name", f"%{name}%")
            .limit(5)
            .execute()
        )
        for med in medicines.data:
            inventory = (
                supabase.table("inventory")
                .select("*, pharmacies(id, name, address, suburb, phone, whatsapp_number, opening_hours)")
                .eq("medicine_id", med["id"])
                .eq("in_stock", True)
                .order("price")
                .execute()
            )
            med["pharmacies"] = inventory.data
            results.append(med)
    return results


async def get_medicine_availability(medicine_id: str) -> List[Dict]:
    result = (
        supabase.table("inventory")
        .select("*, pharmacies(id, name, address, suburb, phone, whatsapp_number, opening_hours)")
        .eq("medicine_id", medicine_id)
        .eq("in_stock", True)
        .order("price")
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Search log helpers
# ---------------------------------------------------------------------------

async def log_search(data: Dict) -> Dict:
    result = supabase.table("search_logs").insert(data).execute()
    return result.data[0] if result.data else {}


# ---------------------------------------------------------------------------
# Inquiry helpers
# ---------------------------------------------------------------------------

async def create_inquiry(data: Dict) -> Dict:
    result = supabase.table("inquiries").insert(data).execute()
    return result.data[0] if result.data else {}


async def list_inquiries(pharmacy_id: str, limit: int = 20) -> List[Dict]:
    result = (
        supabase.table("inquiries")
        .select("*, customers(phone, name), medicines(name)")
        .eq("pharmacy_id", pharmacy_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------

async def get_admin_overview_stats() -> Dict:
    """Get platform-wide overview stats for admin dashboard."""
    pharmacies = supabase.table("pharmacies").select("id, verified").execute()
    users = supabase.table("pharmacy_users").select("id").execute()
    medicines = supabase.table("medicines").select("id").execute()
    searches = supabase.table("search_logs").select("id").execute()

    total_pharmacies = len(pharmacies.data) if pharmacies.data else 0
    active_pharmacies = len([p for p in (pharmacies.data or []) if p.get("verified")])
    total_users = len(users.data) if users.data else 0
    total_medicines = len(medicines.data) if medicines.data else 0
    total_searches = len(searches.data) if searches.data else 0

    # Recent signups (last 30 days)
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
    recent = supabase.table("pharmacies").select("id").gte("created_at", cutoff).execute()
    recent_signups = len(recent.data) if recent.data else 0

    return {
        "total_pharmacies": total_pharmacies,
        "active_pharmacies": active_pharmacies,
        "total_users": total_users,
        "total_medicines": total_medicines,
        "total_searches": total_searches,
        "recent_signups": recent_signups,
    }


async def get_admin_trending_medicines(limit: int = 10) -> list:
    """Get most searched medicines across all pharmacies."""
    result = (
        supabase.table("inventory")
        .select("medicine_id, times_searched, medicines(name)")
        .order("times_searched", desc=True)
        .gt("times_searched", 0)
        .limit(limit)
        .execute()
    )
    seen = set()
    trending = []
    for item in (result.data or []):
        mid = item.get("medicine_id")
        if mid in seen:
            continue
        seen.add(mid)
        med_name = ""
        if isinstance(item.get("medicines"), dict):
            med_name = item["medicines"].get("name", "")
        trending.append({
            "medicine_id": mid,
            "medicine_name": med_name,
            "search_count": item.get("times_searched", 0),
        })
    return trending


async def get_pharmacy_analytics(pharmacy_id: str) -> Optional[Dict]:
    # pharmacy_analytics is a view keyed by name, so look up pharmacy name first
    pharmacy = await get_pharmacy_by_id(pharmacy_id)
    if not pharmacy:
        return None
    result = (
        supabase.table("pharmacy_analytics")
        .select("*")
        .eq("name", pharmacy["name"])
        .execute()
    )
    return result.data[0] if result.data else None


async def get_trending_medicines(pharmacy_id: str, limit: int = 10) -> List[Dict]:
    result = (
        supabase.table("inventory")
        .select("times_searched, last_search_date, medicines(name)")
        .eq("pharmacy_id", pharmacy_id)
        .order("times_searched", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


async def increment_search_count(medicine_id: str, pharmacy_id: str) -> None:
    """Increment the search counter on an inventory item."""
    try:
        item = (
            supabase.table("inventory")
            .select("id, times_searched")
            .eq("medicine_id", medicine_id)
            .eq("pharmacy_id", pharmacy_id)
            .execute()
        )
        if item.data:
            current = item.data[0].get("times_searched", 0) or 0
            supabase.table("inventory").update(
                {"times_searched": current + 1, "last_search_date": "now()"}
            ).eq("id", item.data[0]["id"]).execute()
    except Exception as e:
        logger.error(f"Failed to increment search count: {e}")


# ---------------------------------------------------------------------------
# Rating helpers
# ---------------------------------------------------------------------------

async def create_or_update_rating(data: Dict) -> Dict:
    """Upsert a rating (one per customer per pharmacy)."""
    existing = (
        supabase.table("ratings")
        .select("id")
        .eq("customer_id", data["customer_id"])
        .eq("pharmacy_id", data["pharmacy_id"])
        .execute()
    )
    if existing.data:
        result = (
            supabase.table("ratings")
            .update({"score": data["score"], "comment": data.get("comment")})
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        result = supabase.table("ratings").insert(data).execute()
    return result.data[0] if result.data else {}


async def get_pharmacy_ratings(pharmacy_id: str, limit: int = 20) -> List[Dict]:
    result = (
        supabase.table("ratings")
        .select("*, customers(phone, name)")
        .eq("pharmacy_id", pharmacy_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


async def get_customer_rating_for_pharmacy(customer_id: str, pharmacy_id: str) -> Optional[Dict]:
    result = (
        supabase.table("ratings")
        .select("*")
        .eq("customer_id", customer_id)
        .eq("pharmacy_id", pharmacy_id)
        .execute()
    )
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Pharmacy search helpers (for WhatsApp / customer-facing)
# ---------------------------------------------------------------------------

async def search_pharmacies_by_name(query: str, limit: int = 5) -> List[Dict]:
    """Search active pharmacies by name (fuzzy)."""
    result = (
        supabase.table("pharmacies")
        .select("id, name, address, suburb, city, phone, whatsapp_number, opening_hours, rating, total_reviews, has_delivery, accepts_medical_aid, is_24_hours, latitude, longitude")
        .eq("is_active", True)
        .ilike("name", f"%{query}%")
        .order("rating", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


async def search_pharmacies_by_area(area: str, limit: int = 10) -> List[Dict]:
    """Search active pharmacies by suburb or city."""
    q1 = (
        supabase.table("pharmacies")
        .select("id, name, address, suburb, city, phone, whatsapp_number, opening_hours, rating, total_reviews, has_delivery, accepts_medical_aid, is_24_hours, latitude, longitude")
        .eq("is_active", True)
        .ilike("suburb", f"%{area}%")
        .order("rating", desc=True)
        .limit(limit)
        .execute()
    )
    q2 = (
        supabase.table("pharmacies")
        .select("id, name, address, suburb, city, phone, whatsapp_number, opening_hours, rating, total_reviews, has_delivery, accepts_medical_aid, is_24_hours, latitude, longitude")
        .eq("is_active", True)
        .ilike("city", f"%{area}%")
        .order("rating", desc=True)
        .limit(limit)
        .execute()
    )
    seen = set()
    merged = []
    for p in (q1.data or []) + (q2.data or []):
        if p["id"] not in seen:
            seen.add(p["id"])
            merged.append(p)
    return merged[:limit]


async def get_pharmacy_details(pharmacy_id: str) -> Optional[Dict]:
    """Get full pharmacy details for customer-facing display."""
    result = (
        supabase.table("pharmacies")
        .select("*")
        .eq("id", pharmacy_id)
        .eq("is_active", True)
        .execute()
    )
    return result.data[0] if result.data else None


async def update_customer(customer_id: str, data: Dict) -> Dict:
    result = supabase.table("customers").update(data).eq("id", customer_id).execute()
    return result.data[0] if result.data else {}


# ---------------------------------------------------------------------------
# Saved pharmacies helpers
# ---------------------------------------------------------------------------

async def save_pharmacy_for_customer(customer_id: str, pharmacy_id: str) -> Dict:
    """Save a pharmacy for a customer (idempotent)."""
    existing = (
        supabase.table("saved_pharmacies")
        .select("id")
        .eq("customer_id", customer_id)
        .eq("pharmacy_id", pharmacy_id)
        .execute()
    )
    if existing.data:
        return existing.data[0]
    result = supabase.table("saved_pharmacies").insert({
        "customer_id": customer_id,
        "pharmacy_id": pharmacy_id,
    }).execute()
    return result.data[0] if result.data else {}


async def get_saved_pharmacies(customer_id: str) -> List[Dict]:
    """Get all saved pharmacies for a customer."""
    result = (
        supabase.table("saved_pharmacies")
        .select("pharmacy_id, pharmacies(id, name, address, suburb, city, phone, whatsapp_number, opening_hours, rating, total_reviews, has_delivery, accepts_medical_aid, is_24_hours, latitude, longitude)")
        .eq("customer_id", customer_id)
        .order("saved_at", desc=True)
        .execute()
    )
    return result.data


async def unsave_pharmacy_for_customer(customer_id: str, pharmacy_id: str) -> bool:
    """Remove a saved pharmacy."""
    supabase.table("saved_pharmacies").delete().eq("customer_id", customer_id).eq("pharmacy_id", pharmacy_id).execute()
    return True


async def add_unverified_medicine(name: str, added_by: str = "") -> Optional[Dict]:
    """Insert an unmatched medicine for admin review if it doesn't already exist."""
    try:
        existing = supabase.table("medicines").select("id").ilike("name", name).limit(1).execute()
        if existing.data:
            return existing.data[0]
        result = supabase.table("medicines").insert({"name": name}).execute()
        logger.info(f"[NEW_MEDICINE] \"{name}\" added by user {added_by} — pending admin review")
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Failed to add unverified medicine '{name}': {e}")
        return None


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

async def get_conversation_history(customer_id: str, limit: int = 10) -> List[Dict]:
    result = (
        supabase.table("conversation_history")
        .select("*")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = result.data
    rows.reverse()
    return rows


async def save_conversation_message(data: Dict) -> Dict:
    result = supabase.table("conversation_history").insert(data).execute()
    return result.data[0] if result.data else {}
