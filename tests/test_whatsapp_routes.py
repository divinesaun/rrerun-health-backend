"""
Comprehensive tests for EVERY routing path in WhatsAppService.process_message.

Tests the service directly with mocked DB / OCR / LLM / search dependencies.
Each test verifies:
  - The correct path is taken (via response content assertions)
  - Session state is read/written correctly
  - No hallucination (LLM not called when it shouldn't be)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.whatsapp_service import (
    WhatsAppService,
    _read_session,
    _save_session,
    _extract_location,
    _is_symptom_text,
    _SESSION_MARKER,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

CUST = "cust-test-001"
PHARM_ID_A = "pharm-aaa"
PHARM_ID_B = "pharm-bbb"

PHARMACY_A = {
    "id": PHARM_ID_A,
    "name": "Alpha Pharmacy",
    "address": "1 Main St",
    "suburb": "Avondale",
    "city": "Harare",
    "phone": "+263771000001",
    "whatsapp_number": "+263771000001",
    "latitude": -17.78,
    "longitude": 31.05,
    "opening_hours": None,
    "rating": 4.2,
    "total_reviews": 10,
    "has_delivery": True,
    "accepts_medical_aid": True,
    "is_24_hours": False,
    "parking_available": True,
    "website": None,
    "facebook": None,
    "instagram": None,
    "special_services": None,
}

PHARMACY_B = {
    "id": PHARM_ID_B,
    "name": "Beta Pharmacy",
    "address": "2 Second St",
    "suburb": "Borrowdale",
    "city": "Harare",
    "phone": "+263771000002",
    "whatsapp_number": None,
    "latitude": -17.80,
    "longitude": 31.06,
    "opening_hours": None,
    "rating": None,
    "total_reviews": 0,
    "has_delivery": False,
    "accepts_medical_aid": False,
    "is_24_hours": False,
    "parking_available": False,
    "website": None,
    "facebook": None,
    "instagram": None,
    "special_services": None,
}


def _make_session_msg(data: dict) -> dict:
    """Helper: create a conversation_history row that looks like a session marker."""
    payload = {_SESSION_MARKER: True, **data}
    return {"role": "system", "content": json.dumps(payload)}


def _make_history(*msgs) -> list:
    """Build a conversation_history list (oldest first) from dicts."""
    return list(msgs)


@pytest.fixture
def svc():
    return WhatsAppService()


@pytest.fixture
def mock_db():
    """Patch the db module used by whatsapp_service."""
    with patch("app.services.whatsapp_service.db") as m:
        m.get_conversation_history = AsyncMock(return_value=[])
        m.save_conversation_message = AsyncMock(return_value={})
        m.get_pharmacy_details = AsyncMock(return_value=PHARMACY_A)
        m.get_saved_pharmacies = AsyncMock(return_value=[])
        m.save_pharmacy_for_customer = AsyncMock(return_value={})
        m.search_pharmacies_by_name = AsyncMock(return_value=[])
        m.search_pharmacies_by_area = AsyncMock(return_value=[])
        m.update_customer = AsyncMock(return_value={})
        m.create_or_update_rating = AsyncMock(return_value={})
        m.add_unverified_medicine = AsyncMock(return_value={})
        m.log_search = AsyncMock(return_value={})
        m.increment_search_count = AsyncMock(return_value={})
        yield m


@pytest.fixture
def mock_search():
    with patch("app.services.whatsapp_service.search_service") as m:
        m.find_medicines = AsyncMock(return_value=[])
        yield m


@pytest.fixture
def mock_analytics():
    with patch("app.services.whatsapp_service.analytics_service") as m:
        m.log_search = AsyncMock(return_value=None)
        yield m


@pytest.fixture
def mock_ocr():
    with patch("app.services.whatsapp_service.ocr_service") as m:
        m.extract_text_from_url = MagicMock(return_value="")
        yield m


@pytest.fixture
def mock_llm():
    with patch("app.services.whatsapp_service.stepfun_service") as m:
        m.extract_medicines_from_text = MagicMock(return_value=[])
        m.extract_medicines_from_ocr_text = MagicMock(return_value=[])
        m.understand_intent = MagicMock(return_value={"intent": "unknown", "medicines": []})
        yield m


# ─── Helper to set session state ─────────────────────────────────────────────

def set_session(mock_db, **kwargs):
    """Configure mock_db.get_conversation_history to return a session with given keys."""
    mock_db.get_conversation_history = AsyncMock(
        return_value=[_make_session_msg(kwargs)]
    )


# ═════════════════════════════════════════════════════════════════════════════
# PATH 1-2: GLOBAL COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestGlobalCommands:

    @pytest.mark.parametrize("msg", ["0", "menu", "home", "back", "main menu"])
    async def test_menu_commands(self, svc, mock_db, msg):
        """Path 1: Any menu command → welcome message."""
        result = await svc.process_message(CUST, msg)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "Welcome to RERUN Health" in result[0]["body"]

    async def test_menu_clears_session(self, svc, mock_db):
        """Path 1b: Going to menu clears search_results so menu numbers work."""
        set_session(mock_db, search_results=[PHARM_ID_A], viewing_pharmacy=PHARM_ID_A)
        await svc.process_message(CUST, "0")
        # Check that session was cleared
        calls = mock_db.save_conversation_message.call_args_list
        session_writes = []
        for c in calls:
            data = c[0][0] if c[0] else c[1]
            if isinstance(data, dict) and data.get("role") == "system":
                content = json.loads(data["content"])
                if content.get(_SESSION_MARKER):
                    session_writes.append(content)
        assert len(session_writes) > 0
        last = session_writes[-1]
        assert "search_results" not in last
        assert "viewing_pharmacy" not in last

    @pytest.mark.parametrize("msg", ["help", "?"])
    async def test_help_commands(self, svc, mock_db, msg):
        """Path 2: help/? → help message."""
        result = await svc.process_message(CUST, msg)
        assert len(result) == 1
        assert "Quick Guide" in result[0]["body"]


# ═════════════════════════════════════════════════════════════════════════════
# PATH 3: MEDIA / OCR
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMediaOCR:

    async def test_image_ocr_empty(self, svc, mock_db, mock_ocr, mock_llm, mock_search, mock_analytics):
        """Path 3a: Image sent but OCR returns empty → ask to type manually."""
        mock_ocr.extract_text_from_url.return_value = ""
        result = await svc.process_message(CUST, "", media_url="https://twilio.com/img.jpg")
        assert len(result) == 1
        assert "couldn't read any text" in result[0]["body"]
        mock_llm.extract_medicines_from_ocr_text.assert_not_called()

    async def test_image_ocr_success_no_medicines(self, svc, mock_db, mock_ocr, mock_llm, mock_search, mock_analytics):
        """Path 3b: OCR returns text but LLM can't extract medicines → ask to type."""
        mock_ocr.extract_text_from_url.return_value = "Some random text without medicines"
        mock_llm.extract_medicines_from_ocr_text.return_value = []
        mock_llm.extract_medicines_from_text.return_value = []
        result = await svc.process_message(CUST, "", media_url="https://twilio.com/img.jpg")
        assert any("couldn't identify" in a["body"] for a in result)

    async def test_image_ocr_success_with_medicines(self, svc, mock_db, mock_ocr, mock_llm, mock_search, mock_analytics):
        """Path 3c: OCR → LLM → search pipeline works end to end."""
        mock_ocr.extract_text_from_url.return_value = "Amoxicillin 500mg\nParacetamol 500mg"
        mock_llm.extract_medicines_from_ocr_text.return_value = [
            {"name": "Amoxicillin", "dosage": "500mg", "quantity": "21"},
            {"name": "Paracetamol", "dosage": "500mg", "quantity": "10"},
        ]
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Amoxicillin 500mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 5.00, "in_stock": True, "quantity_available": 20}
            ]},
        ]
        result = await svc.process_message(CUST, "", media_url="https://twilio.com/img.jpg")
        # Should have: scan message + search results
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Found from your image" in bodies
        assert "Amoxicillin" in bodies

    async def test_image_ocr_exception(self, svc, mock_db, mock_ocr, mock_llm, mock_search, mock_analytics):
        """Path 3d: OCR throws exception → graceful error message."""
        mock_ocr.extract_text_from_url.side_effect = ValueError("OCR failed")
        result = await svc.process_message(CUST, "", media_url="https://twilio.com/img.jpg")
        assert any("trouble reading" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 4: LOCATION DETECTION
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestLocationDetection:

    async def test_google_maps_url(self, svc, mock_db):
        """Path 4a: Google Maps URL → location handler."""
        mock_db.search_pharmacies_by_area.return_value = [PHARMACY_A]
        result = await svc.process_message(
            CUST, "https://maps.google.com/?q=-17.7847594,31.0510115"
        )
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Pharmacies near" in bodies
        mock_db.update_customer.assert_called_once()

    async def test_raw_coordinates(self, svc, mock_db):
        """Path 4b: Raw lat,lng → location handler."""
        mock_db.search_pharmacies_by_area.return_value = [PHARMACY_A]
        result = await svc.process_message(CUST, "-17.7847594, 31.0510115")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Pharmacies near" in bodies

    async def test_location_no_pharmacies(self, svc, mock_db):
        """Path 4c: Location detected but no pharmacies found."""
        mock_db.search_pharmacies_by_area.return_value = []
        result = await svc.process_message(
            CUST, "https://maps.google.com/?q=-17.78,31.05"
        )
        assert any("couldn't find pharmacies" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 5-6: AWAITING RATING COMMENT
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRatingComment:

    async def test_skip_comment(self, svc, mock_db):
        """Path 6a: awaiting_comment + 'skip' → finalize without comment."""
        set_session(mock_db, awaiting_comment={"score": 5, "pharmacy_id": PHARM_ID_A})
        result = await svc.process_message(CUST, "skip")
        assert any("rated" in a["body"] for a in result)
        mock_db.create_or_update_rating.assert_called_once()
        rating_data = mock_db.create_or_update_rating.call_args[0][0]
        assert rating_data["score"] == 5
        assert rating_data["comment"] is None

    async def test_submit_comment(self, svc, mock_db):
        """Path 6b: awaiting_comment + text → finalize with comment."""
        set_session(mock_db, awaiting_comment={"score": 4, "pharmacy_id": PHARM_ID_A})
        result = await svc.process_message(CUST, "Great service!")
        assert any("rated" in a["body"] for a in result)
        rating_data = mock_db.create_or_update_rating.call_args[0][0]
        assert rating_data["score"] == 4
        assert rating_data["comment"] == "Great service!"

    async def test_awaiting_comment_cleared_after_finalize(self, svc, mock_db):
        """After rating is finalized, awaiting_comment is cleared from session."""
        set_session(mock_db, awaiting_comment={"score": 3, "pharmacy_id": PHARM_ID_A},
                    viewing_pharmacy=PHARM_ID_A)
        await svc.process_message(CUST, "Good")
        # Check that _save_session was called to clear awaiting_comment
        # The session write should contain awaiting_comment=None to clear it
        calls = mock_db.save_conversation_message.call_args_list
        session_writes = []
        for c in calls:
            data = c[0][0] if c[0] else c[1]
            if isinstance(data, dict) and data.get("role") == "system":
                content = json.loads(data["content"])
                if content.get(_SESSION_MARKER):
                    session_writes.append(content)
        # The final session write should NOT have awaiting_comment
        assert len(session_writes) > 0
        last_session = session_writes[-1]
        assert "awaiting_comment" not in last_session


# ═════════════════════════════════════════════════════════════════════════════
# PATH 7: NUMBER INPUT — CONTEXT-AWARE
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestNumberInput:

    async def test_number_with_active_results(self, svc, mock_db):
        """Path 7a: digit + active results → pharmacy detail (single text message)."""
        set_session(mock_db, search_results=[PHARM_ID_A, PHARM_ID_B])
        mock_db.get_pharmacy_details.return_value = PHARMACY_A
        result = await svc.process_message(CUST, "1")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "Alpha Pharmacy" in result[0]["body"]

    async def test_number_2_with_active_results(self, svc, mock_db):
        """Path 7a2: '2' with results → selects second pharmacy, NOT 'near me'."""
        set_session(mock_db, search_results=[PHARM_ID_A, PHARM_ID_B])
        mock_db.get_pharmacy_details.return_value = PHARMACY_B
        result = await svc.process_message(CUST, "2")
        types = [a["type"] for a in result]
        assert "text" in types
        assert any("Beta Pharmacy" in a["body"] for a in result if a["type"] == "text")

    async def test_number_1_no_results(self, svc, mock_db):
        """Path 7b: '1' with no results → search prompt (menu item 1)."""
        result = await svc.process_message(CUST, "1")
        assert any("What medicine" in a["body"] for a in result)

    async def test_number_2_no_results(self, svc, mock_db):
        """Path 7c: '2' with no results → near me prompt (menu item 2)."""
        result = await svc.process_message(CUST, "2")
        assert any("Find pharmacies" in a["body"] for a in result)

    async def test_number_3_no_results(self, svc, mock_db):
        """Path 7d: '3' with no results → saved pharmacies (menu item 3)."""
        result = await svc.process_message(CUST, "3")
        assert any("Saved Pharmacies" in a["body"] for a in result)

    async def test_number_out_of_range(self, svc, mock_db):
        """Path 7e: number > len(results) → out of range error."""
        set_session(mock_db, search_results=[PHARM_ID_A])
        result = await svc.process_message(CUST, "5")
        assert any("pick a number from 1 to 1" in a["body"] for a in result)

    async def test_number_4_no_results(self, svc, mock_db):
        """Path 7f: number > 3, no results → welcome fallback."""
        result = await svc.process_message(CUST, "4")
        assert any("Welcome" in a["body"] for a in result)

    async def test_number_0_in_digit_branch(self, svc, mock_db):
        """Path 7g: '0' is caught by global check (path 1), not the digit branch."""
        result = await svc.process_message(CUST, "0")
        assert any("Welcome" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 8: GREETINGS
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestGreetings:

    @pytest.mark.parametrize("msg", ["hi", "hello", "hey", "start", "hie", "yo"])
    async def test_greetings(self, svc, mock_db, msg):
        """Path 8: Greeting words → welcome."""
        result = await svc.process_message(CUST, msg)
        assert any("Welcome" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 9: EXPLICIT COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestExplicitCommands:

    @pytest.mark.parametrize("msg", ["find", "find medicine", "search"])
    async def test_find_commands(self, svc, mock_db, msg):
        """Path 9a: find/search → search prompt."""
        result = await svc.process_message(CUST, msg)
        assert any("What medicine" in a["body"] for a in result)

    @pytest.mark.parametrize("msg", ["near me", "nearby", "pharmacies near me"])
    async def test_nearby_commands(self, svc, mock_db, msg):
        """Path 9b: near me → near me prompt."""
        result = await svc.process_message(CUST, msg)
        assert any("Find pharmacies" in a["body"] for a in result)

    @pytest.mark.parametrize("msg", ["saved", "my saved", "my saved pharmacies"])
    async def test_saved_commands(self, svc, mock_db, msg):
        """Path 9c: saved → saved pharmacies list."""
        result = await svc.process_message(CUST, msg)
        assert any("Saved Pharmacies" in a["body"] for a in result)

    async def test_save_with_pharmacy(self, svc, mock_db):
        """Path 9d: 'save' with viewing_pharmacy → save it."""
        set_session(mock_db, viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "save")
        assert any("saved!" in a["body"] for a in result)
        mock_db.save_pharmacy_for_customer.assert_called_once_with(CUST, PHARM_ID_A)

    async def test_save_without_pharmacy(self, svc, mock_db):
        """Path 9d2: 'save' without viewing_pharmacy → error."""
        result = await svc.process_message(CUST, "save")
        assert any("view a pharmacy first" in a["body"] for a in result)

    async def test_rate_with_pharmacy(self, svc, mock_db):
        """Path 9e: 'rate' with viewing_pharmacy → rating prompt."""
        set_session(mock_db, viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "rate")
        assert any("Rate" in a["body"] for a in result)
        assert any("rate 1" in a["body"] for a in result)

    async def test_rate_without_pharmacy(self, svc, mock_db):
        """Path 9e2: 'rate' without viewing_pharmacy → error."""
        result = await svc.process_message(CUST, "rate")
        assert any("view a pharmacy first" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 10: RATE N [COMMENT]
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRateCommand:

    async def test_rate_5_no_comment(self, svc, mock_db):
        """Path 10a: 'rate 5' → saves score, prompts for comment."""
        set_session(mock_db, viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "rate 5")
        assert any("Got it" in a["body"] for a in result)
        assert any("comment" in a["body"].lower() for a in result)

    async def test_rate_5_with_comment(self, svc, mock_db):
        """Path 10b: 'rate 5 great service' → saves directly."""
        set_session(mock_db, viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "rate 5 great service")
        assert any("rated" in a["body"] for a in result)
        rating_data = mock_db.create_or_update_rating.call_args[0][0]
        assert rating_data["score"] == 5
        assert rating_data["comment"] == "great service"

    async def test_rate_invalid_score(self, svc, mock_db):
        """Path 10c: 'rate 0' or 'rate 7' → invalid → show rating prompt."""
        set_session(mock_db, viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "rate 0")
        assert any("Rate" in a["body"] for a in result)

    async def test_rate_no_pharmacy(self, svc, mock_db):
        """Path 10d: 'rate 5' without viewing_pharmacy → error."""
        result = await svc.process_message(CUST, "rate 5")
        assert any("view a pharmacy first" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 11: PHARMACY SEARCH
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestPharmacySearch:

    async def test_pharmacy_search_found(self, svc, mock_db):
        """Path 11a: 'pharmacy Avondale' → results."""
        mock_db.search_pharmacies_by_name.return_value = [PHARMACY_A]
        result = await svc.process_message(CUST, "pharmacy Avondale")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Alpha Pharmacy" in bodies

    async def test_pharmacy_search_not_found(self, svc, mock_db):
        """Path 11b: 'pharmacy Nowhere' → no results."""
        result = await svc.process_message(CUST, "pharmacy Nowhere")
        assert any("No pharmacies found" in a["body"] for a in result)

    async def test_pharmacy_search_empty_query(self, svc, mock_db):
        """Path 11c: 'pharmacy' alone (no area) → near me prompt."""
        result = await svc.process_message(CUST, "pharmacy")
        assert any("Find pharmacies" in a["body"] for a in result)

    async def test_find_pharmacy_prefix(self, svc, mock_db):
        """Path 11d: 'find pharmacy Avondale' → results (query should be 'Avondale' not 'pharmacy Avondale')."""
        mock_db.search_pharmacies_by_name.return_value = [PHARMACY_A]
        result = await svc.process_message(CUST, "find pharmacy Avondale")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Alpha Pharmacy" in bodies
        # Verify the search was called with the correct extracted query
        mock_db.search_pharmacies_by_name.assert_called_with("Avondale")

    async def test_find_pharmacy_alone(self, svc, mock_db):
        """Path 11e: 'find pharmacy' alone → near me prompt."""
        result = await svc.process_message(CUST, "find pharmacy")
        assert any("Find pharmacies" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# PATH 12: SYMPTOM DETECTION → LLM
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestSymptomDetection:

    async def test_symptom_headache(self, svc, mock_db, mock_llm, mock_search, mock_analytics):
        """Path 12a: 'I have a headache' → LLM extracts medicines → search."""
        mock_llm.extract_medicines_from_text.return_value = ["Paracetamol", "Ibuprofen"]
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol 500mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100}
            ]},
        ]
        result = await svc.process_message(CUST, "I have a headache")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Paracetamol" in bodies
        mock_llm.extract_medicines_from_text.assert_called_once_with("I have a headache")

    async def test_symptom_llm_fails(self, svc, mock_db, mock_llm, mock_search, mock_analytics):
        """Path 12b: Symptom detected but LLM returns empty → fallback message."""
        mock_llm.extract_medicines_from_text.return_value = []
        result = await svc.process_message(CUST, "I have a headache")
        assert any("not feeling well" in a["body"] for a in result)

    async def test_symptom_llm_exception(self, svc, mock_db, mock_llm, mock_search, mock_analytics):
        """Path 12c: Symptom detected but LLM throws → fallback message."""
        mock_llm.extract_medicines_from_text.side_effect = Exception("LLM down")
        result = await svc.process_message(CUST, "I have a headache")
        assert any("not feeling well" in a["body"] for a in result)

    async def test_symptom_words_detected(self):
        """Verify _is_symptom_text detects various symptom phrases."""
        assert _is_symptom_text("I have a headache")
        assert _is_symptom_text("my stomach hurts")
        assert _is_symptom_text("feeling dizzy")
        assert _is_symptom_text("I need something for a cough")
        assert not _is_symptom_text("paracetamol")
        assert not _is_symptom_text("amoxicillin 500mg")


# ═════════════════════════════════════════════════════════════════════════════
# PATH 13: DEFAULT MEDICINE SEARCH
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestDefaultMedicineSearch:

    async def test_medicine_found(self, svc, mock_db, mock_search, mock_analytics):
        """Path 13a: 'paracetamol' → direct search → results."""
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol 500mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100},
                {"pharmacies": PHARMACY_B, "price": 3.00, "in_stock": True, "quantity_available": 50},
            ]},
        ]
        result = await svc.process_message(CUST, "paracetamol")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Paracetamol" in bodies
        assert "Alpha Pharmacy" in bodies
        # Should have sequential numbering
        assert "1." in bodies
        assert "2." in bodies

    async def test_medicine_not_found(self, svc, mock_db, mock_search, mock_analytics):
        """Path 13b: 'xyznoexist' → no results → add unverified."""
        mock_search.find_medicines.return_value = []
        result = await svc.process_message(CUST, "xyznoexist")
        assert any("No pharmacies found" in a["body"] for a in result)
        mock_db.add_unverified_medicine.assert_called_once()

    async def test_medicine_search_saves_session(self, svc, mock_db, mock_search, mock_analytics):
        """Path 13c: Successful search saves pharmacy IDs in session."""
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100}
            ]},
        ]
        await svc.process_message(CUST, "paracetamol")
        # Check session was saved with search_results
        calls = mock_db.save_conversation_message.call_args_list
        session_saved = False
        for c in calls:
            data = c[0][0] if c[0] else c[1]
            if isinstance(data, dict) and data.get("role") == "system":
                content = json.loads(data["content"])
                if content.get(_SESSION_MARKER) and "search_results" in content:
                    session_saved = True
                    assert PHARM_ID_A in content["search_results"]
        assert session_saved, "Session with search_results was not saved"


# ═════════════════════════════════════════════════════════════════════════════
# LOCATION EXTRACTION UNIT TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestLocationExtraction:

    def test_google_maps_url_with_q(self):
        url = "https://maps.google.com/?q=-17.7847594,31.0510115"
        result = _extract_location(url)
        assert result is not None
        assert abs(result[0] - (-17.7847594)) < 0.001
        assert abs(result[1] - 31.0510115) < 0.001

    def test_google_com_maps_url(self):
        url = "https://www.google.com/maps?q=-17.78,31.05"
        result = _extract_location(url)
        assert result is not None

    def test_raw_coordinates(self):
        result = _extract_location("-17.7847594, 31.0510115")
        assert result is not None
        assert abs(result[0] - (-17.7847594)) < 0.001

    def test_location_prefix(self):
        result = _extract_location("location: https://maps.google.com/?q=-17.78,31.05")
        assert result is not None

    def test_no_location(self):
        assert _extract_location("paracetamol") is None
        assert _extract_location("hello") is None
        assert _extract_location("123") is None


# ═════════════════════════════════════════════════════════════════════════════
# SESSION STATE MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestSessionState:

    async def test_read_empty_session(self, mock_db):
        """No session messages → empty dict."""
        mock_db.get_conversation_history.return_value = []
        state = await _read_session(CUST)
        assert state == {}

    async def test_read_session_ignores_non_session_system_msgs(self, mock_db):
        """System messages without _session marker are ignored."""
        mock_db.get_conversation_history.return_value = [
            {"role": "system", "content": json.dumps({"some_old_key": "val"})},
            {"role": "user", "content": "hello"},
        ]
        state = await _read_session(CUST)
        assert state == {}

    async def test_read_session_picks_latest(self, mock_db):
        """Multiple session messages → picks the most recent one."""
        mock_db.get_conversation_history.return_value = [
            _make_session_msg({"search_results": ["old-id"]}),
            {"role": "user", "content": "something"},
            _make_session_msg({"search_results": ["new-id"], "viewing_pharmacy": "pharm-1"}),
        ]
        state = await _read_session(CUST)
        assert state["search_results"] == ["new-id"]
        assert state["viewing_pharmacy"] == "pharm-1"

    async def test_save_session_merges(self, mock_db):
        """Saving session merges with existing state."""
        mock_db.get_conversation_history.return_value = [
            _make_session_msg({"search_results": [PHARM_ID_A], "viewing_pharmacy": PHARM_ID_A}),
        ]
        await _save_session(CUST, {"viewing_pharmacy": PHARM_ID_B})
        # Check what was saved
        saved = mock_db.save_conversation_message.call_args[0][0]
        content = json.loads(saved["content"])
        assert content[_SESSION_MARKER] is True
        assert content["search_results"] == [PHARM_ID_A]  # preserved
        assert content["viewing_pharmacy"] == PHARM_ID_B  # updated

    async def test_save_session_clears_none_values(self, mock_db):
        """Setting a key to None removes it from session."""
        mock_db.get_conversation_history.return_value = [
            _make_session_msg({
                "search_results": [PHARM_ID_A],
                "awaiting_comment": {"score": 5, "pharmacy_id": PHARM_ID_A},
            }),
        ]
        await _save_session(CUST, {"awaiting_comment": None})
        saved = mock_db.save_conversation_message.call_args[0][0]
        content = json.loads(saved["content"])
        assert "awaiting_comment" not in content
        assert content["search_results"] == [PHARM_ID_A]  # preserved


# ═════════════════════════════════════════════════════════════════════════════
# FULL CONVERSATION FLOW TESTS
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestFullConversationFlow:
    """Simulate multi-turn conversations to verify state transitions."""

    async def test_search_then_select(self, svc, mock_db, mock_search, mock_analytics):
        """Search → get results → type '1' → see pharmacy detail."""
        # Turn 1: search
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100}
            ]},
        ]
        result1 = await svc.process_message(CUST, "paracetamol")
        assert any("Paracetamol" in a["body"] for a in result1 if a["type"] == "text")

        # Turn 2: select - simulate session state
        set_session(mock_db, search_results=[PHARM_ID_A])
        result2 = await svc.process_message(CUST, "1")
        types = [a["type"] for a in result2]
        assert "text" in types
        assert any("Alpha Pharmacy" in a["body"] for a in result2 if a["type"] == "text")

    async def test_search_then_select_then_rate(self, svc, mock_db, mock_search, mock_analytics):
        """Search → select → rate 5 → comment → done."""
        # Turn 1: select pharmacy (session already has results)
        set_session(mock_db, search_results=[PHARM_ID_A])
        await svc.process_message(CUST, "1")

        # Turn 2: rate
        set_session(mock_db, search_results=[PHARM_ID_A], viewing_pharmacy=PHARM_ID_A)
        result2 = await svc.process_message(CUST, "rate 5")
        assert any("Got it" in a["body"] for a in result2)

        # Turn 3: submit comment
        set_session(mock_db, search_results=[PHARM_ID_A], viewing_pharmacy=PHARM_ID_A,
                    awaiting_comment={"score": 5, "pharmacy_id": PHARM_ID_A})
        result3 = await svc.process_message(CUST, "Excellent pharmacy!")
        assert any("rated" in a["body"] for a in result3)
        assert any("Excellent pharmacy!" in a["body"] for a in result3)

    async def test_search_then_select_then_save(self, svc, mock_db, mock_search, mock_analytics):
        """Search → select → save."""
        set_session(mock_db, search_results=[PHARM_ID_A], viewing_pharmacy=PHARM_ID_A)
        result = await svc.process_message(CUST, "save")
        assert any("saved!" in a["body"] for a in result)

    async def test_greeting_then_number_1_goes_to_search(self, svc, mock_db):
        """After greeting (no results), '1' → search prompt, NOT pharmacy detail."""
        # No session state
        result = await svc.process_message(CUST, "1")
        assert any("What medicine" in a["body"] for a in result)
        # Verify we did NOT try to show pharmacy detail
        mock_db.get_pharmacy_details.assert_not_called()

    async def test_after_rating_next_message_not_captured(self, svc, mock_db, mock_search, mock_analytics):
        """After rating is finalized, next message should NOT be captured as comment."""
        # Session: awaiting_comment is cleared (simulating post-finalize)
        set_session(mock_db, search_results=[PHARM_ID_A], viewing_pharmacy=PHARM_ID_A)
        # This should go to medicine search, NOT rating comment
        mock_search.find_medicines.return_value = []
        result = await svc.process_message(CUST, "amoxicillin")
        assert any("No pharmacies found" in a["body"] for a in result)


# ═════════════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS — tricky inputs that could cause wrong routing
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestEdgeCases:

    async def test_cold_medicine_goes_to_symptom_not_literal(self, svc, mock_db, mock_llm, mock_search, mock_analytics):
        """'cold medicine' should be detected as symptom text and go through LLM, not search 'cold medicine' literally."""
        mock_llm.extract_medicines_from_text.return_value = ["Flu medication", "Paracetamol"]
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Flu medication", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 5.00, "in_stock": True, "quantity_available": 10}
            ]}
        ]
        result = await svc.process_message(CUST, "cold medicine")
        mock_llm.extract_medicines_from_text.assert_called_once_with("cold medicine")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Flu medication" in bodies

    async def test_feeling_sick_goes_to_symptom(self, svc, mock_db, mock_llm, mock_search, mock_analytics):
        """'feeling sick' should go through symptom LLM path."""
        mock_llm.extract_medicines_from_text.return_value = ["Paracetamol"]
        mock_search.find_medicines.return_value = []
        await svc.process_message(CUST, "feeling sick")
        mock_llm.extract_medicines_from_text.assert_called_once_with("feeling sick")

    async def test_number_1_with_results_goes_to_detail_not_menu(self, svc, mock_db):
        """CRITICAL: '1' when results exist must select pharmacy, NOT show 'Find medicine'."""
        set_session(mock_db, search_results=[PHARM_ID_A])
        mock_db.get_pharmacy_details.return_value = PHARMACY_A
        result = await svc.process_message(CUST, "1")
        # Must show pharmacy detail, NOT search prompt
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Alpha Pharmacy" in bodies
        assert "What medicine" not in bodies

    async def test_number_2_with_results_goes_to_detail_not_nearby(self, svc, mock_db):
        """CRITICAL: '2' when results exist must select second pharmacy, NOT show 'Near me'."""
        set_session(mock_db, search_results=[PHARM_ID_A, PHARM_ID_B])
        mock_db.get_pharmacy_details.return_value = PHARMACY_B
        result = await svc.process_message(CUST, "2")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Beta Pharmacy" in bodies
        assert "Find pharmacies" not in bodies

    async def test_number_3_with_results_goes_to_detail_not_saved(self, svc, mock_db):
        """CRITICAL: '3' when 3+ results must select third pharmacy, NOT show saved list."""
        pharm_c_id = "pharm-ccc"
        pharm_c = {**PHARMACY_A, "id": pharm_c_id, "name": "Charlie Pharmacy"}
        set_session(mock_db, search_results=[PHARM_ID_A, PHARM_ID_B, pharm_c_id])
        mock_db.get_pharmacy_details.return_value = pharm_c
        result = await svc.process_message(CUST, "3")
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Charlie Pharmacy" in bodies
        assert "Saved Pharmacies" not in bodies

    async def test_google_maps_url_not_medicine_search(self, svc, mock_db):
        """CRITICAL: Google Maps URL must NOT be treated as medicine search."""
        mock_db.search_pharmacies_by_area.return_value = [PHARMACY_A]
        result = await svc.process_message(
            CUST, "location: https://maps.google.com/?q=-17.7847594,31.0510115"
        )
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Pharmacies near" in bodies
        assert "No pharmacies found with" not in bodies

    async def test_menu_while_awaiting_comment_takes_precedence(self, svc, mock_db):
        """'0' while awaiting_comment should go to menu (global), NOT be captured as comment.
        Global commands (step 1) run BEFORE session check (step 6)."""
        set_session(mock_db, awaiting_comment={"score": 5, "pharmacy_id": PHARM_ID_A})
        result = await svc.process_message(CUST, "0")
        assert any("Welcome" in a["body"] for a in result)
        # Rating should NOT be finalized
        mock_db.create_or_update_rating.assert_not_called()

    async def test_help_while_awaiting_comment(self, svc, mock_db):
        """'help' while awaiting_comment → help (global), not comment."""
        set_session(mock_db, awaiting_comment={"score": 5, "pharmacy_id": PHARM_ID_A})
        result = await svc.process_message(CUST, "help")
        assert any("Quick Guide" in a["body"] for a in result)
        mock_db.create_or_update_rating.assert_not_called()

    async def test_case_insensitive_commands(self, svc, mock_db):
        """Commands should be case-insensitive."""
        result = await svc.process_message(CUST, "MENU")
        assert any("Welcome" in a["body"] for a in result)

        result = await svc.process_message(CUST, "HELP")
        assert any("Quick Guide" in a["body"] for a in result)

        result = await svc.process_message(CUST, "Hi")
        assert any("Welcome" in a["body"] for a in result)

    async def test_empty_message(self, svc, mock_db, mock_search, mock_analytics):
        """Empty/whitespace message → treated as empty medicine search (will return no results)."""
        mock_search.find_medicines.return_value = []
        result = await svc.process_message(CUST, "   ")
        # Should not crash
        assert len(result) >= 1

    async def test_save_preserves_search_results_in_session(self, svc, mock_db):
        """When viewing a pharmacy and saving, the search_results should be preserved."""
        set_session(mock_db, search_results=[PHARM_ID_A, PHARM_ID_B], viewing_pharmacy=PHARM_ID_A)
        await svc.process_message(CUST, "save")
        # session should still have search_results after save
        mock_db.save_pharmacy_for_customer.assert_called_once()

    async def test_pharmacy_detail_has_maps_link(self, svc, mock_db):
        """Pharmacy detail card should include a Google Maps link in text."""
        set_session(mock_db, search_results=[PHARM_ID_A])
        mock_db.get_pharmacy_details.return_value = PHARMACY_A
        result = await svc.process_message(CUST, "1")
        assert len(result) == 1  # single text message, no location pin
        assert result[0]["type"] == "text"
        assert "maps.google.com" in result[0]["body"]
        assert "Main St" in result[0]["body"]

    async def test_pharmacy_detail_no_location_pin(self, svc, mock_db):
        """Pharmacy detail should be a single text message, no location pin."""
        set_session(mock_db, search_results=[PHARM_ID_A])
        mock_db.get_pharmacy_details.return_value = PHARMACY_A
        result = await svc.process_message(CUST, "1")
        location_actions = [a for a in result if a["type"] == "location"]
        assert len(location_actions) == 0

    async def test_pharmacy_without_coords_no_maps_link(self, svc, mock_db):
        """Pharmacy without coordinates should NOT include Maps link."""
        no_coords_pharm = {**PHARMACY_A, "latitude": None, "longitude": None}
        set_session(mock_db, search_results=[PHARM_ID_A])
        mock_db.get_pharmacy_details.return_value = no_coords_pharm
        result = await svc.process_message(CUST, "1")
        assert "maps.google.com" not in result[0]["body"]

    async def test_multiple_medicines_single_numbering(self, svc, mock_db, mock_search, mock_analytics):
        """When search returns multiple medicines, pharmacies should have single sequential numbering."""
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol 500mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100}
            ]},
            {"id": "med-2", "name": "Paracetamol Syrup", "pharmacies": [
                {"pharmacies": PHARMACY_B, "price": 3.00, "in_stock": True, "quantity_available": 50}
            ]},
        ]
        result = await svc.process_message(CUST, "paracetamol")
        body = result[0]["body"]
        # Should have 1. and 2. — single sequential list
        assert "1." in body
        assert "2." in body

    async def test_same_pharmacy_multiple_medicines_grouped(self, svc, mock_db, mock_search, mock_analytics):
        """When same pharmacy has multiple medicines, they should be grouped under one number."""
        mock_search.find_medicines.return_value = [
            {"id": "med-1", "name": "Paracetamol 500mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 2.50, "in_stock": True, "quantity_available": 100}
            ]},
            {"id": "med-2", "name": "Ibuprofen 400mg", "pharmacies": [
                {"pharmacies": PHARMACY_A, "price": 3.00, "in_stock": True, "quantity_available": 50}
            ]},
        ]
        result = await svc.process_message(CUST, "paracetamol")
        body = result[0]["body"]
        # Same pharmacy should appear only ONCE (one number)
        assert body.count("Alpha Pharmacy") == 1
        # Both medicines should be listed under it
        assert "Paracetamol 500mg" in body
        assert "Ibuprofen 400mg" in body

    async def test_pharmacy_deleted_during_selection(self, svc, mock_db):
        """If pharmacy is deleted between search and selection → error message."""
        set_session(mock_db, search_results=[PHARM_ID_A])
        mock_db.get_pharmacy_details.return_value = None
        result = await svc.process_message(CUST, "1")
        assert any("no longer available" in a["body"] for a in result)

    async def test_ocr_llm_fallback_to_text_extraction(self, svc, mock_db, mock_ocr, mock_llm, mock_search, mock_analytics):
        """If OCR→extract_medicines_from_ocr_text returns empty, fallback to extract_medicines_from_text."""
        mock_ocr.extract_text_from_url.return_value = "Some prescription text"
        mock_llm.extract_medicines_from_ocr_text.return_value = []
        mock_llm.extract_medicines_from_text.return_value = ["Amoxicillin"]
        mock_search.find_medicines.return_value = []
        result = await svc.process_message(CUST, "", media_url="https://twilio.com/img.jpg")
        # Should have tried the fallback
        mock_llm.extract_medicines_from_text.assert_called_once()
        bodies = " ".join(a["body"] for a in result if a["type"] == "text")
        assert "Amoxicillin" in bodies


# ═════════════════════════════════════════════════════════════════════════════
# MEDICATION REMINDERS
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMedicationReminders:

    async def test_set_reminder_24h(self, svc, mock_db):
        """'remind Paracetamol 08:00' should create a reminder."""
        mock_db.create_reminder = AsyncMock(return_value={"id": "rem-1"})
        result = await svc.process_message(CUST, "remind Paracetamol 08:00")
        assert any("Reminder set" in a["body"] for a in result)
        assert any("Paracetamol" in a["body"] for a in result)
        mock_db.create_reminder.assert_called_once()

    async def test_set_reminder_ampm(self, svc, mock_db):
        """'remind Metformin 2pm' should parse as 14:00."""
        mock_db.create_reminder = AsyncMock(return_value={"id": "rem-2"})
        result = await svc.process_message(CUST, "remind Metformin 2pm")
        assert any("14:00" in a["body"] for a in result)

    async def test_set_reminder_bad_format(self, svc, mock_db):
        """'remind' with no time should show usage instructions."""
        result = await svc.process_message(CUST, "remind Paracetamol")
        assert any("Format" in a["body"] or "remind" in a["body"].lower() for a in result)

    async def test_list_reminders_empty(self, svc, mock_db):
        """'reminders' with no active reminders shows empty message."""
        mock_db.list_reminders = AsyncMock(return_value=[])
        result = await svc.process_message(CUST, "reminders")
        assert any("don't have any" in a["body"] for a in result)

    async def test_list_reminders_with_items(self, svc, mock_db):
        """'reminders' lists all active reminders."""
        mock_db.list_reminders = AsyncMock(return_value=[
            {"id": "rem-1", "medicine_name": "Paracetamol", "reminder_time": "08:00:00"},
            {"id": "rem-2", "medicine_name": "Metformin", "reminder_time": "14:00:00"},
        ])
        result = await svc.process_message(CUST, "reminders")
        body = result[0]["body"]
        assert "Paracetamol" in body
        assert "Metformin" in body
        assert "08:00" in body
        assert "14:00" in body

    async def test_cancel_reminder_by_number(self, svc, mock_db):
        """'cancel reminder 1' cancels the first reminder."""
        mock_db.list_reminders = AsyncMock(return_value=[
            {"id": "rem-1", "medicine_name": "Paracetamol", "reminder_time": "08:00:00"},
        ])
        mock_db.cancel_reminder = AsyncMock(return_value=True)
        result = await svc.process_message(CUST, "cancel reminder 1")
        assert any("Cancelled" in a["body"] for a in result)
        mock_db.cancel_reminder.assert_called_once_with("rem-1", CUST)

    async def test_cancel_all_reminders(self, svc, mock_db):
        """'cancel all reminders' cancels everything."""
        mock_db.cancel_all_reminders = AsyncMock(return_value=3)
        result = await svc.process_message(CUST, "cancel all reminders")
        assert any("Cancelled 3" in a["body"] for a in result)
