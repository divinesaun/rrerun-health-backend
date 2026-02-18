import pytest
from unittest.mock import patch, MagicMock

from app.services.ocr_service import OCRService


class TestOCRService:
    """Tests for OCR.space text extraction (mock API response)."""

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_success(self, mock_requests):
        """Test successful OCR text extraction from image URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ParsedResults": [{"ParsedText": "Amoxicillin 500mg\nTake 3 times daily"}],
            "IsErroredOnProcessing": False,
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        service = OCRService(api_key="test-key")
        result = service.extract_text_from_url("https://example.com/image.jpg")

        assert "Amoxicillin" in result
        assert "500mg" in result
        mock_requests.get.assert_called_once()

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_error(self, mock_requests):
        """Test OCR processing error handling."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "IsErroredOnProcessing": True,
            "ErrorMessage": ["Image too blurry"],
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        service = OCRService(api_key="test-key")
        with pytest.raises(ValueError, match="OCR error"):
            service.extract_text_from_url("https://example.com/blurry.jpg")

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_empty_results(self, mock_requests):
        """Test OCR returns empty when no text found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ParsedResults": [],
            "IsErroredOnProcessing": False,
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        service = OCRService(api_key="test-key")
        result = service.extract_text_from_url("https://example.com/blank.jpg")
        assert result == ""

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_base64_success(self, mock_requests):
        """Test OCR text extraction from base64 image."""
        import base64

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ParsedResults": [{"ParsedText": "Paracetamol 500mg"}],
            "IsErroredOnProcessing": False,
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_response

        service = OCRService(api_key="test-key")
        fake_b64 = base64.b64encode(b"fake-image-data").decode()
        result = service.extract_text_from_base64(fake_b64)

        assert "Paracetamol" in result
