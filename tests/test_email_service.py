import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.email_service import EmailService


@pytest.fixture
def email_service():
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.GMAIL_ADDRESS = "test@gmail.com"
        mock_settings.GMAIL_APP_PASSWORD = "test app password"
        mock_settings.EMAIL_FROM_NAME = "RERUN Health Test"
        mock_settings.DASHBOARD_URL = "http://localhost:8080"
        svc = EmailService()
    return svc


@pytest.mark.asyncio
async def test_send_pharmacy_welcome(email_service):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email_service.send_pharmacy_welcome(
            to_email="pharmacy@example.com",
            pharmacy_name="HealthPharm Avondale",
            contact_name="John Doe",
            temp_password="TempPass123!",
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["username"] == "test@gmail.com"
        assert call_kwargs["hostname"] == "smtp.gmail.com"
        assert call_kwargs["port"] == 587
        assert call_kwargs["start_tls"] is True


@pytest.mark.asyncio
async def test_send_password_reset(email_service):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email_service.send_password_reset(
            to_email="pharmacy@example.com",
            contact_name="John Doe",
            temp_password="NewTemp456!",
        )
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_admin_notification(email_service):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email_service.send_admin_notification(
            subject="New Pharmacy Registered",
            message="A new pharmacy has been added.",
            details={"Pharmacy": "Test Pharmacy", "City": "Harare"},
        )
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_customer_notification(email_service):
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await email_service.send_customer_notification(
            to_email="customer@example.com",
            message="Your medicine is now available!",
            customer_name="Jane",
            cta_text="View Details",
            cta_url="https://rerun.health",
        )
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_failure_raises(email_service):
    import aiosmtplib
    with patch("aiosmtplib.send", side_effect=aiosmtplib.SMTPException("Connection failed")):
        with pytest.raises(aiosmtplib.SMTPException):
            await email_service.send_pharmacy_welcome(
                to_email="pharmacy@example.com",
                pharmacy_name="Test Pharmacy",
                contact_name="Jane",
                temp_password="pass",
            )


@pytest.mark.asyncio
async def test_app_password_spaces_stripped(email_service):
    """Spaces in the Gmail App Password should be stripped."""
    assert " " not in email_service.gmail_app_password


def test_render_pharmacy_welcome(email_service):
    """Template renders without errors and contains key content."""
    html = email_service._render(
        "pharmacy_welcome.html",
        subject="Test",
        contact_name="Alice",
        pharmacy_name="Alice Pharmacy",
        email="alice@test.com",
        temp_password="secret123",
        login_url="http://localhost:8080",
    )
    assert "Alice" in html
    assert "Alice Pharmacy" in html
    assert "secret123" in html
    assert "http://localhost:8080" in html


def test_render_password_reset(email_service):
    html = email_service._render(
        "password_reset.html",
        subject="Test",
        contact_name="Bob",
        email="bob@test.com",
        temp_password="newpass",
        login_url="http://localhost:8080",
    )
    assert "Bob" in html
    assert "newpass" in html


def test_render_admin_notification(email_service):
    html = email_service._render(
        "admin_notification.html",
        subject="Alert",
        message="Something happened",
        details={"Key": "Value"},
    )
    assert "Something happened" in html
    assert "Value" in html


def test_render_customer_notification(email_service):
    html = email_service._render(
        "customer_notification.html",
        subject="Update",
        customer_name="Charlie",
        message="Your medicine is available",
        cta_text="Check Now",
        cta_url="https://rerun.health",
    )
    assert "Charlie" in html
    assert "Check Now" in html
