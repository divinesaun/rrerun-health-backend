from typing import List, Dict, Optional

from loguru import logger

from app import database as db
from app.utils.helpers import sort_pharmacies_by_distance


class SearchService:
    async def find_medicines(
        self,
        medicine_names: List[str],
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> List[Dict]:
        """Search for medicines by name and return results with pharmacy inventory."""
        results = await db.search_medicines_with_inventory(medicine_names)

        if latitude and longitude:
            for med in results:
                if med.get("pharmacies"):
                    pharmacies = []
                    for inv in med["pharmacies"]:
                        p = inv.get("pharmacies", {})
                        if p:
                            p["price"] = inv.get("price")
                            p["in_stock"] = inv.get("in_stock")
                            p["quantity_available"] = inv.get("quantity_available")
                            pharmacies.append(p)
                    med["pharmacies"] = sort_pharmacies_by_distance(pharmacies, latitude, longitude)

        return results

    async def log_search(
        self,
        customer_id: Optional[str],
        query: str,
        results: List[Dict],
    ) -> None:
        """Log a search to the database for analytics."""
        try:
            medicine_ids = [r.get("id") for r in results if r.get("id")]
            await db.log_search({
                "customer_id": customer_id,
                "query": query,
                "results_count": len(results),
                "medicine_ids": medicine_ids,
            })

            for med in results:
                if med.get("pharmacies"):
                    for inv in med["pharmacies"]:
                        pharmacy_id = inv.get("pharmacy_id") or (inv.get("pharmacies", {}) or {}).get("id")
                        if pharmacy_id and med.get("id"):
                            await db.increment_search_count(med["id"], pharmacy_id)
        except Exception as e:
            logger.error(f"Failed to log search: {e}")


search_service = SearchService()
