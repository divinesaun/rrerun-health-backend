import json
from typing import List, Optional, Dict

import requests as http_requests
from loguru import logger

from app.config import settings


class StepFunService:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.model = model or settings.STEPFUN_MODEL
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://rerun.health",
            "X-Title": "RERUN Health AI",
        }

    def _chat(self, system: str, user: str, history: Optional[List[dict]] = None, label: str = "LLM") -> str:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        logger.info(f"[{label}] REQUEST  system={system[:200]!r}  user={user[:200]!r}  history_len={len(history) if history else 0}")

        try:
            payload = {
                "model": self.model,
                "messages": messages,
            }
            response = http_requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                data=json.dumps(payload),
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.info(f"[{label}] RESPONSE content={content[:500]!r}")
            return content
        except Exception as e:
            logger.error(f"[{label}] ERROR: {e}")
            raise

    def _safe_json_parse(self, text: str, fallback=None):
        """Parse JSON from LLM response, stripping markdown fences if present."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM JSON: {text[:200]}")
            return fallback if fallback is not None else []

    def extract_medicines_from_text(self, query: str) -> List[str]:
        """Extract medicine names from a plain-language customer query."""
        result = self._chat(
            system=(
                "You are a pharmacy assistant. Extract medicine names from the user's message. "
                "Return ONLY a JSON array of medicine name strings. Example: [\"Paracetamol 500mg\", \"Amoxicillin\"]. "
                "If the user describes symptoms, map them to common medicines. Return [] if nothing found."
            ),
            user=query,
            label="EXTRACT_MEDS_TEXT",
        )
        return self._safe_json_parse(result, [])

    def extract_medicines_from_ocr_text(self, ocr_text: str) -> List[Dict]:
        """Parse raw OCR output from a prescription into structured medicine list."""
        result = self._chat(
            system=(
                "You are a pharmacy assistant. Given raw OCR text from a prescription, "
                "extract all medicines with their dosage and quantity. "
                "Return ONLY a JSON array of objects like: "
                '[{"name": "Amoxicillin", "dosage": "500mg", "quantity": "21 tablets"}]. '
                "If nothing is identifiable, return []."
            ),
            user=f"Prescription OCR text:\n{ocr_text}",
            label="EXTRACT_MEDS_OCR",
        )
        return self._safe_json_parse(result, [])

    def understand_intent(self, query: str, history: Optional[List[dict]] = None) -> Dict:
        """Determine the user's intent and any follow-up context."""
        result = self._chat(
            label="UNDERSTAND_INTENT",
            system=(
                "You are the AI brain of a WhatsApp pharmacy bot in Zimbabwe called RERUN Health.\n"
                "Determine the user's intent from their message.\n\n"
                "Return ONLY a JSON object with these keys:\n"
                "- intent: one of: search_medicine, search_pharmacy, select_result, "
                "request_alternatives, rate_pharmacy, greeting, menu, unknown\n"
                "- medicines: list of medicine name strings (empty if not searching)\n"
                "- area: string area/suburb/city name if searching for pharmacies (null otherwise)\n"
                "- selection_index: 1-based int if user is selecting a numbered result (null otherwise)\n"
                "- rating_score: int 1-5 if user is rating (null otherwise)\n"
                "- rating_comment: string comment if rating (null otherwise)\n\n"
                "INTENT RULES:\n"
                "- If user mentions a medicine name, symptom, or ailment → search_medicine\n"
                "- If user says 'pharmacy near X', 'pharmacies in Y', 'find pharmacy Z' → search_pharmacy\n"
                "- If user sends a number like '1', '2', '3' → select_result\n"
                "- If user asks for alternatives/substitutes → request_alternatives (include original medicine in medicines)\n"
                "- If user says 'rate 4' or 'rate 5 great service' → rate_pharmacy\n"
                "- If user says hi/hello/hey/start → greeting\n"
                "- If user says menu/help/options → menu\n\n"
                "SYMPTOM MAPPING:\n"
                "- headache/pain → [\"Paracetamol\", \"Ibuprofen\"]\n"
                "- cold/flu → [\"Flu medication\", \"Paracetamol\"]\n"
                "- allergy → [\"Cetirizine\", \"Loratadine\"]\n"
                "- stomach/nausea → [\"Omeprazole\", \"Buscopan\"]\n\n"
                'Example: {"intent": "search_medicine", "medicines": ["Paracetamol"], "area": null, '
                '"selection_index": null, "rating_score": null, "rating_comment": null}'
            ),
            user=query,
            history=history,
        )
        parsed = self._safe_json_parse(result, {})
        if not isinstance(parsed, dict):
            return {"intent": "unknown", "medicines": [], "selection_index": None}
        return parsed

    def format_whatsapp_response(self, medicines: list, pharmacies: list) -> str:
        """Generate a friendly WhatsApp-formatted reply from search results."""
        context = json.dumps({"medicines": medicines, "pharmacies": pharmacies}, default=str)
        return self._chat(
            label="FORMAT_RESPONSE",
            system=(
                "You are a WhatsApp pharmacy bot. Format search results into a friendly, "
                "concise WhatsApp message using emojis. List pharmacies with name, price, stock status, "
                "address, and phone. End with 'Reply with a number to get more info'. "
                "If no results found, say so politely and suggest trying a different name."
            ),
            user=context,
        )


    def fix_inventory_csv(self, raw_csv: str) -> str:
        """Correct a malformed inventory CSV so it matches the expected format."""
        return self._chat(
            label="FIX_CSV",
            system=(
                "You are a data-cleaning assistant for a pharmacy inventory system.\n"
                "The user will give you the raw text of a CSV file that may have wrong "
                "column names, missing columns, bad formatting, or jumbled data.\n\n"
                "## REQUIRED OUTPUT FORMAT\n"
                "A valid CSV with exactly these 4 columns in this order:\n"
                "  medicine_name,price,in_stock,quantity_available\n\n"
                "## COLUMN DATA TYPES\n"
                "| Column              | Type    | Description                              | Examples                    |\n"
                "| medicine_name       | string  | Full medicine name with strength/form     | Paracetamol 500mg, Salbutamol Inhaler |\n"
                "| price               | number  | Positive decimal, no currency symbol      | 2.99, 12.50, 0.00          |\n"
                "| in_stock            | boolean | Lowercase true or false ONLY              | true, false                 |\n"
                "| quantity_available  | integer | Positive integer or empty if out of stock | 150, 45, (empty)            |\n\n"
                "## EXAMPLE CORRECT OUTPUT\n"
                "medicine_name,price,in_stock,quantity_available\n"
                "Paracetamol 500mg,2.99,true,150\n"
                "Ibuprofen 400mg,4.49,true,200\n"
                "Omeprazole 20mg,6.50,false,\n"
                "Salbutamol Inhaler,18.99,true,60\n\n"
                "## RULES\n"
                "- NEVER change, correct, or rename the actual medicine names the user provided. Keep them EXACTLY as uploaded.\n"
                "- NEVER change price values. Only reformat them (e.g. remove '$' or 'USD', keep the number).\n"
                "- NEVER add or remove data rows. Every row in the input must appear in the output.\n"
                "- Map columns: anything resembling medicine/drug/product name → medicine_name, "
                "cost/price/amount → price, stock/available/status → in_stock, qty/quantity/count → quantity_available.\n"
                "- Convert stock values: yes/Yes/YES/1/in stock/available → true; no/No/NO/0/out of stock/unavailable → false.\n"
                "- If quantity is missing and in_stock is false, leave quantity_available empty.\n"
                "- If quantity is missing and in_stock is true, leave quantity_available empty (do NOT guess).\n"
                "- If price is missing, default to 0.00.\n"
                "- Return ONLY the corrected CSV text. No markdown fences, no explanation, no commentary."
            ),
            user=f"Here is the raw CSV:\n{raw_csv}",
        )


stepfun_service = StepFunService()
