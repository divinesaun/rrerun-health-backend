import pytest
from unittest.mock import AsyncMock, patch

from app.services.search_service import SearchService


@pytest.mark.asyncio
class TestSearchService:
    """Tests for search algorithm accuracy."""

    @patch("app.services.search_service.db")
    async def test_find_medicines_by_name(self, mock_db):
        """Search returns medicines with pharmacy inventory."""
        mock_db.search_medicines_with_inventory = AsyncMock(return_value=[
            {
                "id": "med-1",
                "name": "Paracetamol 500mg",
                "pharmacies": [
                    {
                        "pharmacy_id": "p1",
                        "price": 1.50,
                        "in_stock": True,
                        "quantity_available": "In Stock",
                        "pharmacies": {"id": "p1", "name": "HealthPharm", "address": "Avondale"},
                    },
                    {
                        "pharmacy_id": "p2",
                        "price": 2.00,
                        "in_stock": True,
                        "quantity_available": "10+",
                        "pharmacies": {"id": "p2", "name": "MedPlus", "address": "Borrowdale"},
                    },
                ],
            }
        ])

        service = SearchService()
        results = await service.find_medicines(["Paracetamol"])

        assert len(results) == 1
        assert results[0]["name"] == "Paracetamol 500mg"
        assert len(results[0]["pharmacies"]) == 2

    @patch("app.services.search_service.db")
    async def test_find_medicines_empty(self, mock_db):
        """Search returns empty list when no medicines match."""
        mock_db.search_medicines_with_inventory = AsyncMock(return_value=[])

        service = SearchService()
        results = await service.find_medicines(["NonexistentMedicine"])
        assert results == []

    @patch("app.services.search_service.db")
    async def test_find_medicines_multiple_names(self, mock_db):
        """Search handles multiple medicine names."""
        mock_db.search_medicines_with_inventory = AsyncMock(return_value=[
            {"id": "m1", "name": "Paracetamol 500mg", "pharmacies": []},
            {"id": "m2", "name": "Ibuprofen 400mg", "pharmacies": []},
        ])

        service = SearchService()
        results = await service.find_medicines(["Paracetamol", "Ibuprofen"])
        assert len(results) == 2

    @patch("app.services.search_service.db")
    async def test_log_search(self, mock_db):
        """Search logging doesn't raise on failure."""
        mock_db.log_search = AsyncMock(side_effect=Exception("DB error"))
        mock_db.increment_search_count = AsyncMock()

        service = SearchService()
        # Should not raise
        await service.log_search("cust-1", "paracetamol", [{"id": "m1"}])
