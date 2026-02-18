import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestWhatsAppWebhook:
    """Tests for WhatsApp webhook parsing (Twilio form data)."""

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.analytics_service")
    @patch("app.routers.whatsapp.search_service")
    @patch("app.routers.whatsapp.stepfun_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_text_message_search(
        self, mock_db, mock_auth, mock_stepfun, mock_search, mock_analytics, mock_twilio, client
    ):
        """Test processing a plain text medicine search."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_stepfun.understand_intent = MagicMock(
            return_value={"intent": "search_medicine", "medicines": ["Paracetamol"], "selection_index": None}
        )
        mock_search.find_medicines = AsyncMock(return_value=[{"id": "med-1", "name": "Paracetamol", "pharmacies": []}])
        mock_analytics.log_search = AsyncMock()
        mock_stepfun.format_whatsapp_response = MagicMock(return_value="Found Paracetamol at 1 pharmacy")
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM123"})

        response = await client.post(
            "/webhook/whatsapp",
            data={
                "From": "whatsapp:+263771234567",
                "Body": "paracetamol",
                "NumMedia": "0",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_twilio.send_message.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.analytics_service")
    @patch("app.routers.whatsapp.search_service")
    @patch("app.routers.whatsapp.stepfun_service")
    @patch("app.routers.whatsapp.ocr_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_image_message_ocr(
        self, mock_db, mock_auth, mock_ocr, mock_stepfun, mock_search, mock_analytics, mock_twilio, client
    ):
        """Test processing a prescription image via OCR."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_ocr.extract_text_from_url = MagicMock(return_value="Amoxicillin 500mg x21")
        mock_stepfun.extract_medicines_from_ocr_text = MagicMock(
            return_value=[{"name": "Amoxicillin", "dosage": "500mg", "quantity": "21"}]
        )
        mock_search.find_medicines = AsyncMock(return_value=[{"id": "med-2", "name": "Amoxicillin", "pharmacies": []}])
        mock_analytics.log_search = AsyncMock()
        mock_stepfun.format_whatsapp_response = MagicMock(return_value="Found Amoxicillin")
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM456"})

        response = await client.post(
            "/webhook/whatsapp",
            data={
                "From": "whatsapp:+263771234567",
                "Body": "",
                "NumMedia": "1",
                "MediaUrl0": "https://api.twilio.com/image.jpg",
            },
        )
        assert response.status_code == 200
        mock_ocr.extract_text_from_url.assert_called_once_with("https://api.twilio.com/image.jpg")

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.stepfun_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_greeting_intent(self, mock_db, mock_auth, mock_stepfun, mock_twilio, client):
        """Test that a greeting returns a welcome message."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_stepfun.understand_intent = MagicMock(
            return_value={"intent": "greeting", "medicines": [], "selection_index": None}
        )
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM789"})

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "Hi", "NumMedia": "0"},
        )
        assert response.status_code == 200
        call_args = mock_twilio.send_message.call_args
        assert "Welcome" in call_args[0][1] or "welcome" in call_args[0][1].lower()


@pytest.mark.asyncio
class TestWhatsAppStatus:
    async def test_status_callback(self, client):
        response = await client.post(
            "/webhook/whatsapp/status",
            data={"MessageSid": "SM123", "MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "received"
