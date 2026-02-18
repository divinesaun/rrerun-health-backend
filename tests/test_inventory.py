import pytest
from unittest.mock import AsyncMock, patch
import io

from app.utils.security import create_access_token


def make_pharmacy_token(user_id="user-123", pharmacy_id="pharm-456"):
    return create_access_token({"sub": user_id, "pharmacy_id": pharmacy_id, "role": "pharmacy"})


@pytest.mark.asyncio
class TestInventoryCRUD:
    """Tests for inventory CRUD operations."""

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_list_inventory(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.list_inventory = AsyncMock(return_value=[
            {"id": "inv-1", "medicine_id": "m1", "price": 1.50, "in_stock": True},
        ])

        token = make_pharmacy_token()
        response = await client.get(
            "/api/pharmacy/inventory",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert len(response.json()["inventory"]) == 1

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_add_inventory(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.add_inventory_item = AsyncMock(return_value={
            "id": "inv-new",
            "pharmacy_id": "pharm-456",
            "medicine_id": "m1",
            "price": 2.50,
            "in_stock": True,
        })

        token = make_pharmacy_token()
        response = await client.post(
            "/api/pharmacy/inventory",
            json={"medicine_id": "m1", "price": 2.50, "in_stock": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["item"]["price"] == 2.50

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_update_inventory(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.update_inventory_item = AsyncMock(return_value={
            "id": "inv-1",
            "price": 3.00,
            "in_stock": True,
        })

        token = make_pharmacy_token()
        response = await client.put(
            "/api/pharmacy/inventory/inv-1",
            json={"price": 3.00},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_delete_inventory(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.delete_inventory_item = AsyncMock()

        token = make_pharmacy_token()
        response = await client.delete(
            "/api/pharmacy/inventory/inv-1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
class TestCSVUpload:
    """Tests for CSV upload validation and error handling."""

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_valid_csv_upload(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.find_medicine_by_name = AsyncMock(return_value={"id": "m1", "name": "Paracetamol 500mg"})
        mock_router_db.upsert_inventory = AsyncMock(return_value={})

        csv_content = "medicine_name,price,in_stock,quantity_available\nParacetamol 500mg,1.50,true,In Stock\n"
        token = make_pharmacy_token()
        response = await client.post(
            "/api/pharmacy/inventory/bulk-upload",
            files={"file": ("inventory.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert "Paracetamol 500mg" in response.json()["success"]

    @patch("app.utils.security.db")
    @patch("app.routers.pharmacy.db")
    async def test_csv_missing_medicine(self, mock_router_db, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)
        mock_router_db.find_medicine_by_name = AsyncMock(return_value=None)

        csv_content = "medicine_name,price,in_stock\nFakeMedicine,5.00,true\n"
        token = make_pharmacy_token()
        response = await client.post(
            "/api/pharmacy/inventory/bulk-upload",
            files={"file": ("inventory.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert "Not found: FakeMedicine" in response.json()["errors"]

    @patch("app.utils.security.db")
    async def test_csv_missing_columns(self, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)

        csv_content = "wrong_column,price\nTest,1.00\n"
        token = make_pharmacy_token()
        response = await client.post(
            "/api/pharmacy/inventory/bulk-upload",
            files={"file": ("bad.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    @patch("app.utils.security.db")
    async def test_invalid_csv_file(self, mock_sec_db, client, sample_pharmacy_user):
        mock_sec_db.get_pharmacy_user_by_id = AsyncMock(return_value=sample_pharmacy_user)

        token = make_pharmacy_token()
        response = await client.post(
            "/api/pharmacy/inventory/bulk-upload",
            files={"file": ("bad.csv", io.BytesIO(b"\x00\x01\x02"), "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
