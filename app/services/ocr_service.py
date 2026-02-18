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

    def extract_text_from_url(self, image_url: str) -> str:
        """Send a Twilio-hosted image URL to OCR.space and return extracted text."""
        payload = {
            "apikey": self.api_key,
            "url": image_url,
            "language": "eng",
            "OCREngine": "2",
            "scale": "true",
            "isTable": "false",
        }
        try:
            response = requests.get(self.OCR_API_URL, params=payload, timeout=30)
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

            return parsed_results[0].get("ParsedText", "")
        except ValueError:
            raise
        except requests.RequestException as e:
            logger.error(f"OCR.space request failed: {e}")
            raise ValueError(f"OCR service unavailable: {e}")

    def extract_text_from_base64(self, image_base64: str, filename: str = "prescription.jpg") -> str:
        """Send a base64-encoded image to OCR.space and return extracted text."""
        image_bytes = base64.b64decode(image_base64)
        try:
            response = requests.post(
                self.OCR_UPLOAD_URL,
                files={"filename": (filename, io.BytesIO(image_bytes))},
                data={
                    "apikey": self.api_key,
                    "language": "eng",
                    "OCREngine": "2",
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("IsErroredOnProcessing"):
                error_msg = result.get("ErrorMessage", ["Unknown error"])
                raise ValueError(f"OCR error: {error_msg}")

            parsed_results = result.get("ParsedResults", [])
            if not parsed_results:
                return ""

            return parsed_results[0].get("ParsedText", "")
        except requests.RequestException as e:
            logger.error(f"OCR.space upload request failed: {e}")
            raise ValueError(f"OCR service unavailable: {e}")


ocr_service = OCRService()
