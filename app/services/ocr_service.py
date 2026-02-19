import base64
import io

import requests
from loguru import logger

from app.config import settings


class OCRService:
    OCR_API_URL = "https://api.ocr.space/parse/imageurl"
    OCR_UPLOAD_URL = "https://api.ocr.space/parse/image"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.OCRSPACE_API_KEY

    def _download_twilio_media(self, media_url: str) -> bytes:
        """Download media from Twilio using HTTP Basic Auth.

        Twilio media URLs require authentication — OCR.space cannot
        fetch them directly. We download first, then upload the bytes.
        """
        try:
            resp = requests.get(
                media_url,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                timeout=30,
            )
            resp.raise_for_status()
            logger.info(f"Downloaded Twilio media: {len(resp.content)} bytes, type={resp.headers.get('Content-Type')}")
            return resp.content
        except requests.RequestException as e:
            logger.error(f"Failed to download Twilio media {media_url}: {e}")
            raise ValueError(f"Could not download image: {e}")

    def extract_text_from_url(self, image_url: str) -> str:
        """Extract text from a Twilio-hosted image URL.

        Downloads the image with Twilio auth first, then uploads
        the raw bytes to OCR.space for processing.
        """
        image_bytes = self._download_twilio_media(image_url)
        return self._ocr_from_bytes(image_bytes)

    def _ocr_from_bytes(self, image_bytes: bytes, filename: str = "prescription.jpg") -> str:
        """Upload raw image bytes to OCR.space and return extracted text."""
        try:
            response = requests.post(
                self.OCR_UPLOAD_URL,
                files={"filename": (filename, io.BytesIO(image_bytes))},
                data={
                    "apikey": self.api_key,
                    "language": "eng",
                    "OCREngine": "2",
                    "scale": "true",
                    "isTable": "false",
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("IsErroredOnProcessing"):
                error_msg = result.get("ErrorMessage", ["Unknown error"])
                logger.error(f"OCR.space processing error: {error_msg}")
                raise ValueError(f"OCR error: {error_msg}")

            parsed_results = result.get("ParsedResults", [])
            if not parsed_results:
                logger.warning("OCR.space returned no parsed results")
                return ""

            text = parsed_results[0].get("ParsedText", "")
            logger.info(f"OCR extracted {len(text)} chars: {text[:200]}")
            return text
        except ValueError:
            raise
        except requests.RequestException as e:
            logger.error(f"OCR.space upload request failed: {e}")
            raise ValueError(f"OCR service unavailable: {e}")

    def extract_text_from_base64(self, image_base64: str, filename: str = "prescription.jpg") -> str:
        """Send a base64-encoded image to OCR.space and return extracted text."""
        image_bytes = base64.b64decode(image_base64)
        return self._ocr_from_bytes(image_bytes, filename)


ocr_service = OCRService()
