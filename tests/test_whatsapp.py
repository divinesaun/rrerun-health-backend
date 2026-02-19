import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestWhatsAppWebhook:
    """Tests for WhatsApp webhook — text-based response actions."""

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_text_message_search(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test processing a plain text medicine search returns text actions."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "💊 *1 pharmacy* with *Paracetamol*\n..."},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM123"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "paracetamol", "NumMedia": "0"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_twilio.send_message.assert_called()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_image_message_ocr(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test processing a prescription image returns scan + results."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "📸 I scanned your image and found: *Amoxicillin*. Searching..."},
            {"type": "text", "body": "💊 *1 pharmacy* with *Amoxicillin*\n..."},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM456"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "", "NumMedia": "1", "MediaUrl0": "https://api.twilio.com/image.jpg"},
        )
        assert response.status_code == 200
        mock_wa.process_message.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_greeting_sends_welcome_text(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that a greeting sends the welcome text message."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "👋 *Welcome to RERUN Health!*\n..."},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM789"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "Hi", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_message.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_pharmacy_detail_sends_location_then_text(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that viewing a pharmacy sends location pin then info card."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "location", "lat": -17.83, "lng": 31.05, "label": "City Pharmacy", "address": "Avondale, Harare"},
            {"type": "text", "body": "🏥 *City Pharmacy*\n..."},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM100"})
        mock_twilio.send_location = AsyncMock(return_value={"sid": "SM101"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "1", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_location.assert_called_once()
        mock_twilio.send_message.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_rating_with_comment_prompt(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that rating sends star confirmation + comment prompt."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "⭐⭐⭐⭐⭐ Thanks!\n\nLeave a comment? Type it now or reply *skip*"},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM200"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "rate 5", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_message.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_menu_returns_welcome(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that '0' returns the main menu welcome text."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "👋 *Welcome to RERUN Health!*\n..."},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM300"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "0", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_message.assert_called_once()


@pytest.mark.asyncio
class TestWhatsAppStatus:
    async def test_status_callback(self, client):
        response = await client.post(
            "/webhook/whatsapp/status",
            data={"MessageSid": "SM123", "MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "received"
