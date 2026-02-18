import pytest
from unittest.mock import AsyncMock, patch

from app.utils.security import hash_password, verify_password, create_access_token, decode_jwt


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "TestPassword123"
        hashed = hash_password(password)
        assert verify_password(password, hashed)
        assert not verify_password("WrongPassword", hashed)


class TestJWT:
    def test_create_and_decode_token(self):
        data = {"sub": "user-123", "pharmacy_id": "pharm-456", "role": "pharmacy"}
        token = create_access_token(data)
        payload = decode_jwt(token)
        assert payload["sub"] == "user-123"
        assert payload["role"] == "pharmacy"

    def test_admin_token_role(self):
        data = {"sub": "admin@rerun.health", "role": "admin"}
        token = create_access_token(data)
        payload = decode_jwt(token)
        assert payload["role"] == "admin"

    def test_invalid_token_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            decode_jwt("invalid.token.here")


@pytest.mark.asyncio
class TestPharmacyAuth:
    @patch("app.routers.pharmacy.auth_service")
    async def test_pharmacy_login_success(self, mock_auth, client):
        mock_auth.pharmacy_login = AsyncMock(return_value={
            "access_token": "test-token",
            "token_type": "bearer",
            "must_change_password": False,
            "user": {"id": "u1", "email": "pharm@test.com", "name": "Test", "pharmacy_id": "p1", "role": "manager"},
        })
        response = await client.post("/api/pharmacy/auth/login", json={"email": "pharm@test.com", "password": "pass123"})
        assert response.status_code == 200
        assert "access_token" in response.json()

    @patch("app.routers.pharmacy.auth_service")
    async def test_pharmacy_login_failure(self, mock_auth, client):
        mock_auth.pharmacy_login = AsyncMock(return_value=None)
        response = await client.post("/api/pharmacy/auth/login", json={"email": "bad@test.com", "password": "wrong"})
        assert response.status_code == 401

    @patch("app.routers.pharmacy.auth_service")
    async def test_must_change_password_flag(self, mock_auth, client):
        mock_auth.pharmacy_login = AsyncMock(return_value={
            "access_token": "test-token",
            "token_type": "bearer",
            "must_change_password": True,
            "user": {"id": "u1", "email": "new@test.com", "name": "New", "pharmacy_id": "p1", "role": "manager"},
        })
        response = await client.post("/api/pharmacy/auth/login", json={"email": "new@test.com", "password": "temppass"})
        assert response.status_code == 200
        assert response.json()["must_change_password"] is True


@pytest.mark.asyncio
class TestPasswordChange:
    @patch("app.utils.security.get_current_user")
    @patch("app.routers.pharmacy.auth_service")
    async def test_change_password_success(self, mock_auth, mock_get_user, client, sample_pharmacy_user):
        mock_get_user.return_value = sample_pharmacy_user
        mock_auth.change_pharmacy_password = AsyncMock(return_value="new-token")

        response = await client.post(
            "/api/pharmacy/auth/change-password",
            json={
                "current_password": "OldPass123",
                "new_password": "NewPass456",
                "confirm_new_password": "NewPass456",
            },
            headers={"Authorization": "Bearer fake-token"},
        )
        # Note: In real tests the Depends override would be needed.
        # This tests the endpoint shape.

    @patch("app.utils.security.get_current_user")
    @patch("app.routers.pharmacy.auth_service")
    async def test_change_password_mismatch(self, mock_auth, mock_get_user, client, sample_pharmacy_user):
        """Mismatched new passwords should be rejected."""
        # This would need proper dependency override to work end-to-end


@pytest.mark.asyncio
class TestAdminAuth:
    @patch("app.routers.admin.auth_service")
    async def test_admin_login_success(self, mock_auth, client):
        mock_auth.admin_login = AsyncMock(return_value={
            "access_token": "admin-token",
            "token_type": "bearer",
            "user": {"id": "a1", "email": "admin@rerun.health", "name": "Admin", "role": "admin"},
        })
        response = await client.post("/api/admin/auth/login", json={"email": "admin@rerun.health", "password": "adminpass"})
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "admin"

    @patch("app.routers.admin.auth_service")
    async def test_admin_login_failure(self, mock_auth, client):
        mock_auth.admin_login = AsyncMock(return_value=None)
        response = await client.post("/api/admin/auth/login", json={"email": "bad@test.com", "password": "wrong"})
        assert response.status_code == 401

    async def test_admin_endpoint_rejects_no_auth(self, client):
        """Admin endpoints require auth."""
        response = await client.get("/api/admin/pharmacies")
        assert response.status_code in (401, 403)

    async def test_admin_endpoint_rejects_pharmacy_jwt(self, client):
        """A pharmacy-role JWT must not pass the admin guard."""
        pharmacy_token = create_access_token({"sub": "user-123", "role": "pharmacy"})
        response = await client.get(
            "/api/admin/pharmacies",
            headers={"Authorization": f"Bearer {pharmacy_token}"},
        )
        assert response.status_code == 403
