import base64

import pytest
from unittest.mock import patch, MagicMock

from app.services.ocr_service import OCRService


class TestOCRService:
    """Tests for OCR.space text extraction (mock API response).

    extract_text_from_url now does TWO HTTP calls:
      1. requests.get  → download image from Twilio with auth
      2. requests.post → upload bytes to OCR.space
    Both must be mocked.
    """

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_success(self, mock_requests):
        """Test successful OCR text extraction from image URL."""
        # Mock step 1: Twilio download
        download_resp = MagicMock()
        download_resp.content = b"fake-image-bytes"
        download_resp.raise_for_status = MagicMock()
        download_resp.headers = {"Content-Type": "image/jpeg"}
        mock_requests.get.return_value = download_resp

        # Mock step 2: OCR.space upload
        ocr_resp = MagicMock()
        ocr_resp.json.return_value = {
            "ParsedResults": [{"ParsedText": "Amoxicillin 500mg\nTake 3 times daily"}],
            "IsErroredOnProcessing": False,
        }
        ocr_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = ocr_resp

        service = OCRService(api_key="test-key")
        result = service.extract_text_from_url("https://api.twilio.com/image.jpg")

        assert "Amoxicillin" in result
        assert "500mg" in result
        mock_requests.get.assert_called_once()   # Twilio download
        mock_requests.post.assert_called_once()  # OCR.space upload

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_error(self, mock_requests):
        """Test OCR processing error handling."""
        download_resp = MagicMock()
        download_resp.content = b"fake-image-bytes"
        download_resp.raise_for_status = MagicMock()
        download_resp.headers = {"Content-Type": "image/jpeg"}
        mock_requests.get.return_value = download_resp

        ocr_resp = MagicMock()
        ocr_resp.json.return_value = {
            "IsErroredOnProcessing": True,
            "ErrorMessage": ["Image too blurry"],
        }
        ocr_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = ocr_resp

        service = OCRService(api_key="test-key")
        with pytest.raises(ValueError, match="OCR error"):
            service.extract_text_from_url("https://api.twilio.com/blurry.jpg")

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_url_empty_results(self, mock_requests):
        """Test OCR returns empty when no text found."""
        download_resp = MagicMock()
        download_resp.content = b"fake-image-bytes"
        download_resp.raise_for_status = MagicMock()
        download_resp.headers = {"Content-Type": "image/jpeg"}
        mock_requests.get.return_value = download_resp

        ocr_resp = MagicMock()
        ocr_resp.json.return_value = {
            "ParsedResults": [],
            "IsErroredOnProcessing": False,
        }
        ocr_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = ocr_resp

        service = OCRService(api_key="test-key")
        result = service.extract_text_from_url("https://api.twilio.com/blank.jpg")
        assert result == ""

    @patch("app.services.ocr_service.requests")
    def test_extract_text_from_base64_success(self, mock_requests):
        """Test OCR text extraction from base64 image."""
        ocr_resp = MagicMock()
        ocr_resp.json.return_value = {
            "ParsedResults": [{"ParsedText": "Paracetamol 500mg"}],
            "IsErroredOnProcessing": False,
        }
        ocr_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = ocr_resp

        service = OCRService(api_key="test-key")
        fake_b64 = base64.b64encode(b"fake-image-data").decode()
        result = service.extract_text_from_base64(fake_b64)

        assert "Paracetamol" in result

    @patch("app.services.ocr_service.requests")
    def test_twilio_download_failure(self, mock_requests):
        """Test that Twilio media download failure raises ValueError."""
        import requests as real_requests
        mock_requests.get.side_effect = real_requests.RequestException("Connection refused")
        mock_requests.RequestException = real_requests.RequestException

        service = OCRService(api_key="test-key")
        with pytest.raises(ValueError, match="Could not download image"):
            service.extract_text_from_url("https://api.twilio.com/image.jpg")
