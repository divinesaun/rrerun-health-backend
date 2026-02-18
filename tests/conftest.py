import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_db():
    """Patch the database module for unit tests."""
    with patch("app.database.supabase") as mock_supabase:
        yield mock_supabase


@pytest.fixture
def mock_twilio():
    with patch("app.services.twilio_service.twilio_service") as mock:
        mock.send_message = AsyncMock(return_value={"sid": "SM123", "status": "queued"})
        yield mock


@pytest.fixture
def mock_ocr():
    with patch("app.services.ocr_service.ocr_service") as mock:
        mock.extract_text_from_url = MagicMock(return_value="Amoxicillin 500mg\nParacetamol 500mg")
        yield mock


@pytest.fixture
def mock_stepfun():
    with patch("app.services.stepfun_service.stepfun_service") as mock:
        mock.extract_medicines_from_text = MagicMock(return_value=["Paracetamol 500mg"])
        mock.extract_medicines_from_ocr_text = MagicMock(
            return_value=[{"name": "Amoxicillin", "dosage": "500mg", "quantity": "21 tablets"}]
        )
        mock.understand_intent = MagicMock(
            return_value={"intent": "search_medicine", "medicines": ["Paracetamol"], "selection_index": None}
        )
        mock.format_whatsapp_response = MagicMock(
            return_value="Found 1 pharmacy with Paracetamol 500mg:\n1. TestPharm - $1.50"
        )
        yield mock


@pytest.fixture
def sample_pharmacy_user():
    return {
        "id": "user-123",
        "email": "pharmacy@test.com",
        "name": "Test User",
        "pharmacy_id": "pharm-456",
        "password_hash": "$2b$12$LJ3m4ys5RkXvYzQGkJxKxePvF5v3KfJyAqgYk.Kzq3dHzQD8bO3Km",
        "role": "manager",
        "must_change_password": False,
        "created_at": "2025-01-01T00:00:00",
    }


@pytest.fixture
def sample_admin():
    return {
        "id": "admin-001",
        "email": "admin@rerun.health",
        "name": "RERUN Admin",
        "password_hash": "$2b$12$LJ3m4ys5RkXvYzQGkJxKxePvF5v3KfJyAqgYk.Kzq3dHzQD8bO3Km",
        "role": "admin",
    }
