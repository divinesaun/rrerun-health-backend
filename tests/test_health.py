import pytest


@pytest.mark.asyncio
class TestHealthCheck:
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "RERUN Health AI"

    async def test_root_endpoint(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert "RERUN Health AI" in response.json()["message"]
