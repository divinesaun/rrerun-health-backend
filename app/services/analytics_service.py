from typing import Optional, List, Dict

from loguru import logger

from app import database as db


class AnalyticsService:
    async def log_search(
        self,
        customer_id: Optional[str],
        query: str,
        results: List[Dict],
    ) -> None:
        """Log a customer search for analytics."""
        try:
            await db.log_search({
                "customer_id": customer_id,
                "query": query,
                "results_count": len(results),
            })
        except Exception as e:
            logger.error(f"Failed to log search analytics: {e}")

    async def get_pharmacy_stats(self, pharmacy_id: str) -> Dict:
        """Get overview stats for a pharmacy dashboard."""
        analytics = await db.get_pharmacy_analytics(pharmacy_id)
        trending = await db.get_trending_medicines(pharmacy_id)
        inquiries = await db.list_inquiries(pharmacy_id)

        return {
            "overview": analytics or {},
            "trending_medicines": trending,
            "recent_inquiries": inquiries,
        }

    async def get_trending(self, pharmacy_id: str, limit: int = 10) -> List[Dict]:
        """Get most searched medicines for a pharmacy this week."""
        return await db.get_trending_medicines(pharmacy_id, limit)


analytics_service = AnalyticsService()
