import pytest
from unittest.mock import AsyncMock, patch

from app.utils.security import create_access_token


@pytest.mark.asyncio
class TestAdminPharmacyCreation:
    """Test admin pharmacy creation: record created, temp password generated, email triggered."""

    @patch("app.routers.admin.admin_service")
    @patch("app.routers.admin.db")
    @patch("app.utils.security.db")
    async def test_create_pharmacy(self, mock_sec_db, mock_db, mock_admin_svc, client, sample_admin):
        """Admin can create a pharmacy and initial user account."""
        mock_sec_db.get_admin_by_email = AsyncMock(return_value=sample_admin)

        mock_admin_svc.create_pharmacy_with_user = AsyncMock(return_value={
            "pharmacy": {"id": "pharm-new", "name": "TestPharm", "address": "123 Test St"},
            "user": {"id": "user-new", "email": "pharm@test.com", "name": "Owner"},
            "email_sent": True,
        })

        admin_token = create_access_token({"sub": "admin@rerun.health", "role": "admin"})
        response = await client.post(
            "/api/admin/pharmacies",
            json={
                "name": "TestPharm",
                "address": "123 Test St",
                "email": "pharm@test.com",
                "contact_name": "Owner",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pharmacy"]["name"] == "TestPharm"
        assert data["email_sent"] is True

    @patch("app.routers.admin.admin_service")
    @patch("app.routers.admin.db")
    @patch("app.utils.security.db")
    async def test_resend_credentials(self, mock_sec_db, mock_db, mock_admin_svc, client, sample_admin):
        """Admin can resend credentials to a pharmacy."""
        mock_sec_db.get_admin_by_email = AsyncMock(return_value=sample_admin)
        mock_admin_svc.resend_credentials = AsyncMock(return_value={
            "email_sent": True,
            "user_email": "pharm@test.com",
        })

        admin_token = create_access_token({"sub": "admin@rerun.health", "role": "admin"})
        response = await client.post(
            f"/api/admin/pharmacies/pharm-123/resend-credentials",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        assert response.json()["email_sent"] is True


@pytest.mark.asyncio
class TestAdminUserManagement:
    @patch("app.routers.admin.admin_service")
    @patch("app.routers.admin.db")
    @patch("app.utils.security.db")
    async def test_reset_user_password(self, mock_sec_db, mock_db, mock_admin_svc, client, sample_admin):
        """Admin-triggered password reset sends email."""
        mock_sec_db.get_admin_by_email = AsyncMock(return_value=sample_admin)
        mock_admin_svc.reset_user_password = AsyncMock(return_value={"email_sent": True})

        admin_token = create_access_token({"sub": "admin@rerun.health", "role": "admin"})
        response = await client.post(
            "/api/admin/users/user-123/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        assert response.json()["email_sent"] is True

    @patch("app.routers.admin.db")
    @patch("app.utils.security.db")
    async def test_delete_user(self, mock_sec_db, mock_db, client, sample_admin):
        """Admin can delete a pharmacy user."""
        mock_sec_db.get_admin_by_email = AsyncMock(return_value=sample_admin)
        mock_db.get_pharmacy_user_by_id = AsyncMock(return_value={"id": "user-123", "email": "test@test.com"})
        mock_db.delete_pharmacy_user = AsyncMock()

        admin_token = create_access_token({"sub": "admin@rerun.health", "role": "admin"})
        response = await client.delete(
            "/api/admin/users/user-123",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
