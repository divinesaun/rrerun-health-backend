import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestWhatsAppWebhook:
    """Tests for WhatsApp webhook — structured response actions."""

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_text_message_search(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test processing a plain text medicine search returns actions."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "💊 Found 1 pharmacy with *Paracetamol*"},
            {"type": "interactive", "template": "results_nav"},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM123"})
        mock_twilio.send_interactive = AsyncMock(return_value={"sid": "SM124"})
        mock_twilio.get_results_nav_template = MagicMock(return_value="HX_nav")

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
        """Test processing a prescription image returns actions."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "📸 Scanned your prescription: Amoxicillin"},
            {"type": "interactive", "template": "results_nav"},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM456"})
        mock_twilio.send_interactive = AsyncMock(return_value={"sid": "SM457"})
        mock_twilio.get_results_nav_template = MagicMock(return_value="HX_nav")

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
    async def test_greeting_sends_welcome_interactive(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that a greeting sends a welcome interactive template."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "interactive", "template": "welcome"},
        ])
        mock_twilio.send_interactive = AsyncMock(return_value={"sid": "SM789"})
        mock_twilio.get_welcome_template = MagicMock(return_value="HX_welcome")

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "Hi", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.get_welcome_template.assert_called_once()
        mock_twilio.send_interactive.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_pharmacy_detail_sends_location(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that viewing a pharmacy sends a location card + actions."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "🏥 *City Pharmacy*\n..."},
            {"type": "location", "lat": -17.83, "lng": 31.05, "label": "City Pharmacy", "address": "Avondale, Harare"},
            {"type": "interactive", "template": "pharmacy_actions"},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM100"})
        mock_twilio.send_location = AsyncMock(return_value={"sid": "SM101"})
        mock_twilio.send_interactive = AsyncMock(return_value={"sid": "SM102"})
        mock_twilio.get_pharmacy_actions_template = MagicMock(return_value="HX_actions")

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "1", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_location.assert_called_once()

    @patch("app.routers.whatsapp.twilio_service")
    @patch("app.routers.whatsapp.whatsapp_service")
    @patch("app.routers.whatsapp.auth_service")
    @patch("app.routers.whatsapp.db")
    async def test_rating_sends_post_rating_nav(self, mock_db, mock_auth, mock_wa, mock_twilio, client):
        """Test that rating sends confirmation + post-rating navigation."""
        mock_auth.get_or_create_customer = AsyncMock(return_value={"id": "cust-1", "phone": "+263771234567"})
        mock_db.get_conversation_history = AsyncMock(return_value=[])
        mock_db.save_conversation_message = AsyncMock(return_value={})
        mock_wa.process_message = AsyncMock(return_value=[
            {"type": "text", "body": "✅ Thanks! You rated *City Pharmacy* ⭐⭐⭐⭐⭐ (5/5)."},
            {"type": "interactive", "template": "post_rating"},
        ])
        mock_twilio.send_message = AsyncMock(return_value={"sid": "SM200"})
        mock_twilio.send_interactive = AsyncMock(return_value={"sid": "SM201"})
        mock_twilio.get_post_rating_template = MagicMock(return_value="HX_post_rating")

        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+263771234567", "Body": "rate 5 Great!", "NumMedia": "0"},
        )
        assert response.status_code == 200
        mock_twilio.send_message.assert_called()
        mock_twilio.send_interactive.assert_called()


@pytest.mark.asyncio
class TestWhatsAppStatus:
    async def test_status_callback(self, client):
        response = await client.post(
            "/webhook/whatsapp/status",
            data={"MessageSid": "SM123", "MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "received"
