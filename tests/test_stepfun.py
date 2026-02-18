import pytest
from unittest.mock import patch, MagicMock

from app.services.stepfun_service import StepFunService


def _mock_openrouter_response(content: str) -> MagicMock:
    """Create a mock requests.Response with the given content as an OpenRouter chat response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


class TestStepFunService:
    """Tests for Step 3.5 Flash medicine extraction and intent parsing (mock OpenRouter)."""

    @patch("app.services.stepfun_service.http_requests.post")
    def test_extract_medicines_from_text(self, mock_post):
        """Test medicine name extraction from plain text."""
        mock_post.return_value = _mock_openrouter_response('["Paracetamol 500mg", "Ibuprofen"]')

        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service.extract_medicines_from_text("I need paracetamol and ibuprofen")

        assert isinstance(result, list)
        assert "Paracetamol 500mg" in result
        assert "Ibuprofen" in result
        mock_post.assert_called_once()

    @patch("app.services.stepfun_service.http_requests.post")
    def test_extract_medicines_from_ocr_text(self, mock_post):
        """Test medicine extraction from raw OCR output."""
        mock_post.return_value = _mock_openrouter_response(
            '[{"name": "Amoxicillin", "dosage": "500mg", "quantity": "21 tablets"}]'
        )

        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service.extract_medicines_from_ocr_text("Amoxicillin 500mg x21")

        assert isinstance(result, list)
        assert result[0]["name"] == "Amoxicillin"
        assert result[0]["dosage"] == "500mg"

    @patch("app.services.stepfun_service.http_requests.post")
    def test_understand_intent_search(self, mock_post):
        """Test intent parsing for a medicine search query."""
        mock_post.return_value = _mock_openrouter_response(
            '{"intent": "search_medicine", "medicines": ["Paracetamol"], "selection_index": null}'
        )

        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service.understand_intent("paracetamol")

        assert result["intent"] == "search_medicine"
        assert "Paracetamol" in result["medicines"]

    @patch("app.services.stepfun_service.http_requests.post")
    def test_understand_intent_select(self, mock_post):
        """Test intent parsing for a selection."""
        mock_post.return_value = _mock_openrouter_response(
            '{"intent": "select_result", "medicines": [], "selection_index": 2}'
        )

        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service.understand_intent("2")

        assert result["intent"] == "select_result"
        assert result["selection_index"] == 2

    @patch("app.services.stepfun_service.http_requests.post")
    def test_safe_json_parse_with_markdown_fences(self, mock_post):
        """Test that markdown code fences are stripped before JSON parse."""
        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service._safe_json_parse('```json\n["Paracetamol"]\n```')
        assert result == ["Paracetamol"]

    @patch("app.services.stepfun_service.http_requests.post")
    def test_safe_json_parse_fallback(self, mock_post):
        """Test fallback when JSON parsing fails."""
        service = StepFunService(api_key="test", base_url="http://test", model="test-model")
        result = service._safe_json_parse("not valid json", fallback=[])
        assert result == []
