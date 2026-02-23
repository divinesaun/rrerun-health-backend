"""
WhatsApp conversation orchestrator — built from scratch.

Session state is persisted in conversation_history as system messages.
The routing order is critical — session-aware checks come BEFORE menu options
so that numbers select from active results instead of triggering menu items.

Routing priority (strict order):
  1. Global commands: 0/menu/home/back → welcome
  2. Global commands: help/? → help
  3. Media → download with Twilio auth → OCR → LLM → search
  4. Location detection: Google Maps URL / coordinates → search nearby
  5. Session state: awaiting_comment → handle comment
  6. Active results + digit → select pharmacy from results
  7. Pharmacy detail commands: rate/save/back
  8. Greetings: hi/hello/hey/start
  9. Text commands: find/near me/saved/pharmacy X
  10. Symptom detection via LLM → extract medicine names → search
  11. Default: treat as medicine name → search directly
"""

import json
import math
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Zimbabwe uses Central Africa Time (UTC+2)
CAT = timezone(timedelta(hours=2))

from loguru import logger

from app import database as db
from app.services.stepfun_service import stepfun_service
from app.services.search_service import search_service
from app.services.analytics_service import analytics_service
from app.services.ocr_service import ocr_service

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Regex to detect Google Maps URLs or raw coordinates
_LOCATION_RE = re.compile(
    r"(?:location:\s*)?(?:https?://(?:www\.)?(?:google\.com/maps|maps\.google\.com|goo\.gl/maps)\S*[?&]q?=?(-?\d+\.?\d*),\s*(-?\d+\.?\d*))"
    r"|(-?\d{1,3}\.\d{3,}),\s*(-?\d{1,3}\.\d{3,})",
    re.IGNORECASE,
)

# Simple symptom keywords — if message contains these AND no obvious medicine name, use LLM
_SYMPTOM_WORDS = {
    "headache", "pain", "fever", "cold", "flu", "cough", "sore throat",
    "allergy", "allergies", "stomach", "nausea", "vomiting", "diarrhea",
    "infection", "swelling", "rash", "itch", "itching", "dizzy", "tired",
    "ache", "hurt", "burning", "cramp", "cramps", "runny nose", "blocked nose",
    "chest pain", "back pain", "toothache", "earache", "heartburn",
    "i have", "i need something for", "what can i take", "feeling",
}


# ═══════════════════════════════════════════════════════════════════════════
# Response builder helpers
# ═══════════════════════════════════════════════════════════════════════════

def _text(body: str) -> dict:
    return {"type": "text", "body": body}

def _location(lat: float, lng: float, label: str, address: str = "") -> dict:
    return {"type": "location", "lat": lat, "lng": lng, "label": label, "address": address}

def _stars(score: int) -> str:
    return "⭐" * score

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two lat/lon points."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ═══════════════════════════════════════════════════════════════════════════
# Opening hours helpers
# ═══════════════════════════════════════════════════════════════════════════

def _parse_opening_hours(raw) -> Optional[dict]:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "mon" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _is_pharmacy_open(hours_data: Optional[dict]) -> Optional[bool]:
    if not hours_data:
        return None
    now = datetime.now(CAT)
    day_key = list(DAY_MAP.keys())[now.weekday()]
    day = hours_data.get(day_key)
    if not day or not day.get("open"):
        return False
    try:
        current = now.strftime("%H:%M")
        return day.get("from", "00:00") <= current <= day.get("to", "23:59")
    except Exception:
        return None


def _fmt_time_12h(t: str) -> str:
    try:
        h, m = t.split(":")
        hour = int(h)
        ampm = "PM" if hour >= 12 else "AM"
        h12 = 12 if hour == 0 else (hour - 12 if hour > 12 else hour)
        return f"{h12}:{m}{ampm}"
    except Exception:
        return t


def _fmt_opening_hours_detail(hours_data: Optional[dict]) -> str:
    if not hours_data:
        return ""
    lines = []
    for day_key, idx in DAY_MAP.items():
        d = hours_data.get(day_key, {})
        label = DAY_LABELS[idx]
        if d.get("open"):
            lines.append(f"  {label}  {_fmt_time_12h(d.get('from', '08:00'))} – {_fmt_time_12h(d.get('to', '17:00'))}")
        else:
            lines.append(f"  {label}  Closed")
    return "\n".join(lines)


def _open_status_badge(hours_data: Optional[dict]) -> str:
    is_open = _is_pharmacy_open(hours_data)
    if is_open is True:
        return "🟢 Open Now"
    elif is_open is False:
        if hours_data:
            now = datetime.now(CAT)
            keys = list(DAY_MAP.keys())
            for offset in range(1, 8):
                next_day = keys[(now.weekday() + offset) % 7]
                d = hours_data.get(next_day, {})
                if d.get("open"):
                    return f"🔴 Closed (Opens {DAY_LABELS[(now.weekday() + offset) % 7]} {_fmt_time_12h(d.get('from', '08:00'))})"
        return "🔴 Closed"
    return ""


def _stock_badge(in_stock, qty) -> str:
    if not in_stock:
        return "❌ Out of Stock"
    try:
        q = int(qty) if qty else None
    except (ValueError, TypeError):
        q = None
    if q is not None and q <= 5:
        return f"⚠️ Low Stock ({q} left)"
    if q is not None:
        return f"✅ In Stock ({q}+)"
    return "✅ In Stock"


def _is_symptom_text(text: str) -> bool:
    """Heuristic: does this look like a symptom description rather than a medicine name?"""
    lower = text.lower()
    for kw in _SYMPTOM_WORDS:
        if kw in lower:
            return True
    return False


def _extract_location(text: str) -> Optional[Tuple[float, float]]:
    """Try to extract lat,lng from a Google Maps URL or raw coordinates."""
    m = _LOCATION_RE.search(text)
    if m:
        lat = m.group(1) or m.group(3)
        lng = m.group(2) or m.group(4)
        if lat and lng:
            try:
                return float(lat), float(lng)
            except ValueError:
                pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Message formatting
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_pharmacy_line(idx: int, p: dict, medicines_info: list = None) -> str:
    """Format a single pharmacy in the results list.

    medicines_info: optional list of dicts with keys name, price, in_stock, quantity_available
    """
    hours_data = _parse_opening_hours(p.get("opening_hours"))
    status = _open_status_badge(hours_data)

    header = f"{idx}. {status} *{p.get('name', 'Unknown')}*" if status else f"{idx}. *{p.get('name', 'Unknown')}*"
    lines = [header]

    # Medicine lines (when grouped by pharmacy)
    if medicines_info:
        for mi in medicines_info:
            price_str = f"${mi['price']}" if mi.get("price") is not None else ""
            stock_str = _stock_badge(mi.get("in_stock", True), mi.get("quantity_available"))
            lines.append(f"   💊 {mi['name']} — {price_str} {stock_str}")

    # Address
    addr = p.get("address", "")
    suburb = p.get("suburb", "")
    loc_str = ", ".join(filter(None, [addr, suburb]))
    if loc_str:
        lines.append(f"   📍 {loc_str}")

    # Phone
    phone = p.get("phone") or p.get("whatsapp_number")
    if phone:
        lines.append(f"   📞 {phone}")

    return "\n".join(lines)


def _fmt_pharmacy_detail(p: dict) -> str:
    """Format the full pharmacy detail card."""
    hours_data = _parse_opening_hours(p.get("opening_hours"))
    status = _open_status_badge(hours_data)

    lines = [f"🏥 *{p.get('name', 'Unknown')}*"]
    if status:
        lines.append(status)
    lines.append("")

    # Address
    loc = ", ".join(filter(None, [p.get("address", ""), p.get("suburb", ""), p.get("city", "")]))
    if loc:
        lines.append(f"📍 {loc}")
        lines.append("")

    # Phone
    phone = p.get("phone")
    if phone:
        lines.append(f"📞 {phone}")
    wa = p.get("whatsapp_number")
    if wa and wa != phone:
        lines.append(f"💬 wa.me/{wa.strip().replace(' ', '').replace('+', '')}")
    if phone or wa:
        lines.append("")

    # Opening Hours
    if hours_data:
        lines.append("*🕐 Hours*")
        lines.append(_fmt_opening_hours_detail(hours_data))
        lines.append("")

    # Services — only show TRUE flags
    services = []
    if p.get("accepts_medical_aid"):
        services.append("💳 Accepts Medical Aid")
    if p.get("has_delivery"):
        services.append("🚚 Delivery Available")
    if p.get("is_24_hours"):
        services.append("🌙 Open 24 Hours")
    if p.get("parking_available"):
        services.append("🅿️ Parking Available")
    special = p.get("special_services")
    if special:
        services.append(f"ℹ️ {special}")
    if services:
        for s in services:
            lines.append(s)
        lines.append("")

    # Rating
    rating = p.get("rating")
    reviews = p.get("total_reviews", 0)
    if rating:
        full = int(float(rating))
        rating_fmt = f"{float(rating):.1f}"
        lines.append(f"{'⭐' * full} {rating_fmt}/5.0 ({reviews} review{'s' if reviews != 1 else ''})")
        lines.append("")

    # Google Maps link (after reviews)
    lat, lng = p.get("latitude"), p.get("longitude")
    if lat and lng:
        lines.append(f"🗺️ https://maps.google.com/?q={lat},{lng}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_*rate 1-5* to rate · *save* to bookmark_")
    lines.append("_Type a medicine name to search again_")
    lines.append("_Reply *0* for main menu_")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Session state helpers
#
# Session data is stored as a SINGLE system message in conversation_history
# tagged with "_session": true.  Every write reads the current state first,
# merges updates, and writes a new consolidated message so all keys live in
# one place.  This prevents state from being "lost" as messages accumulate.
# ═══════════════════════════════════════════════════════════════════════════

_SESSION_MARKER = "_session"


async def _read_session(customer_id: str) -> dict:
    """Read the most recent consolidated session state.

    Returns a dict that may contain:
      search_results   — list of pharmacy IDs from last search
      viewing_pharmacy — pharmacy ID currently being viewed
      awaiting_comment — {score, pharmacy_id} if waiting for rating comment
    """
    rows = await db.get_conversation_history(customer_id, limit=30)
    for msg in reversed(rows):
        if msg.get("role") != "system":
            continue
        try:
            data = json.loads(msg.get("content", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get(_SESSION_MARKER):
            # Return all keys except the marker itself
            return {k: v for k, v in data.items() if k != _SESSION_MARKER}
    return {}


async def _save_session(customer_id: str, updates: dict) -> None:
    """Merge *updates* into the current session and write a new consolidated message.

    To remove a key, set it to None in updates — it will be stripped out.
    """
    current = await _read_session(customer_id)
    current.update(updates)
    # Strip None values (used to explicitly clear keys like awaiting_comment)
    cleaned = {k: v for k, v in current.items() if v is not None}
    cleaned[_SESSION_MARKER] = True
    await db.save_conversation_message({
        "customer_id": customer_id,
        "role": "system",
        "content": json.dumps(cleaned),
    })
    logger.debug(f"[SESSION] customer={customer_id} state={cleaned}")


# ═══════════════════════════════════════════════════════════════════════════
# WhatsApp Service — the main class
# ═══════════════════════════════════════════════════════════════════════════

class WhatsAppService:

    WELCOME = (
        "👋 *Welcome to RERUN Health!*\n"
        "I help you find medicines at pharmacies near you.\n\n"
        "*What would you like to do?*\n\n"
        "1️⃣ 💊 Find a medicine\n"
        "2️⃣ 📍 Pharmacies near me\n"
        "3️⃣ 💾 My saved pharmacies\n"
        "4️⃣ ⏰ My medication reminders\n"
        "5️⃣ ⭐ Upgrade to Pro\n\n"
        "_Just type a medicine name to get started!_\n"
        "_Reply *0* anytime for this menu_"
    )

    HELP = (
        "ℹ️ *RERUN Health — Quick Guide*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💊 Type any *medicine name* to search\n"
        "🤒 Describe *symptoms* and I'll suggest medicines\n"
        "📸 Send a *prescription photo* to scan\n"
        "📍 Type *pharmacy [area]* to find nearby\n"
        "⭐ Type *rate 1-5* after viewing a pharmacy\n"
        "💾 Type *save* to bookmark a pharmacy\n\n"
        "⏰ *Medication Reminders:*\n"
        "  _remind [medicine] [time]_ — set a reminder\n"
        "  _reminders_ — view your reminders\n"
        "  _cancel reminder [number]_ — cancel one\n\n"
        "⭐ Type *pro* to learn about Pro mode\n\n"
        "_Reply *0* for main menu_"
    )

    SEARCH_PROMPT = (
        "💊 *What medicine do you need?*\n\n"
        "You can:\n"
        "• Type a medicine name (e.g. _paracetamol_)\n"
        "• Describe symptoms (e.g. _I have a headache_)\n"
        "• Send a prescription 📸 photo\n\n"
        "_Reply *0* for main menu_"
    )

    NEAR_ME_PROMPT = (
        "📍 *Find pharmacies near you*\n\n"
        "Type an area name, e.g.:\n"
        "  _pharmacy Avondale_\n"
        "  _pharmacy Borrowdale_\n\n"
        "_Reply *0* for main menu_"
    )

    # ── Main entry point ─────────────────────────────────────────────────

    async def process_message(
        self,
        customer_id: str,
        message: str,
        media_url: Optional[str] = None,
        history: Optional[List[dict]] = None,
    ) -> List[dict]:
        """Route incoming message and return list of text/location actions."""

        text = message.strip()
        lower = text.lower()

        # ── 1. GLOBAL: menu / back — clears session so menu numbers 1/2/3 work ──
        if lower in ("0", "menu", "home", "back", "main menu"):
            logger.info(f"[ROUTE] customer={customer_id} path=GLOBAL_MENU input={lower!r}")
            await _save_session(customer_id, {
                "search_results": None,
                "viewing_pharmacy": None,
                "awaiting_comment": None,
            })
            return [_text(self.WELCOME)]

        # ── 2. GLOBAL: help ──
        if lower in ("help", "?"):
            logger.info(f"[ROUTE] customer={customer_id} path=GLOBAL_HELP input={lower!r}")
            return [_text(self.HELP)]

        # ── 3. Media → OCR pipeline ──
        if media_url:
            logger.info(f"[ROUTE] customer={customer_id} path=MEDIA_OCR url={media_url[:80]}")
            return await self._handle_image(customer_id, media_url)

        # ── 4. Location detection ──
        coords = _extract_location(text)
        if coords:
            logger.info(f"[ROUTE] customer={customer_id} path=LOCATION coords={coords}")
            return await self._handle_location(customer_id, coords)

        # ── 5. Read session state for context-aware routing ──
        session = await _read_session(customer_id)
        logger.debug(f"[ROUTE] customer={customer_id} session_keys={list(session.keys())} input={text[:80]!r}")

        # ── 6. Awaiting rating comment? ──
        if session.get("awaiting_comment"):
            if lower == "skip":
                logger.info(f"[ROUTE] customer={customer_id} path=RATING_SKIP")
                ac = session["awaiting_comment"]
                return await self._finalize_rating(customer_id, ac["score"], None, ac["pharmacy_id"])
            else:
                logger.info(f"[ROUTE] customer={customer_id} path=RATING_COMMENT text={text[:80]!r}")
                ac = session["awaiting_comment"]
                return await self._finalize_rating(customer_id, ac["score"], text, ac["pharmacy_id"])

        # ── 7. Number input — context-aware ──
        if lower.isdigit():
            num = int(lower)
            results = session.get("search_results")
            if results and 1 <= num <= len(results):
                logger.info(f"[ROUTE] customer={customer_id} path=SELECT_RESULT num={num} pharmacy={results[num-1]}")
                return await self._show_pharmacy_detail(customer_id, results[num - 1])
            # If no active results and 1-3, treat as menu
            if num == 0:
                logger.info(f"[ROUTE] customer={customer_id} path=GLOBAL_MENU input='0'")
                return [_text(self.WELCOME)]
            if num == 1 and not results:
                logger.info(f"[ROUTE] customer={customer_id} path=MENU_1_FIND (no results)")
                return [_text(self.SEARCH_PROMPT)]
            if num == 2 and not results:
                logger.info(f"[ROUTE] customer={customer_id} path=MENU_2_NEARBY (no results)")
                return [_text(self.NEAR_ME_PROMPT)]
            if num == 3 and not results:
                logger.info(f"[ROUTE] customer={customer_id} path=MENU_3_SAVED (no results)")
                return await self._show_saved_pharmacies(customer_id)
            if num == 4 and not results:
                logger.info(f"[ROUTE] customer={customer_id} path=MENU_4_REMINDERS (no results)")
                return await self._handle_list_reminders(customer_id)
            if num == 5 and not results:
                logger.info(f"[ROUTE] customer={customer_id} path=MENU_5_PRO (no results)")
                return await self._handle_pro_info(customer_id)
            # Out of range
            if results:
                logger.info(f"[ROUTE] customer={customer_id} path=NUM_OUT_OF_RANGE num={num} max={len(results)}")
                return [_text(f"Please pick a number from 1 to {len(results)}.\n\n_Reply *0* for main menu_")]
            logger.info(f"[ROUTE] customer={customer_id} path=NUM_NO_CONTEXT num={num}")
            return [_text(self.WELCOME)]

        # ── 8. Greetings ──
        if lower in ("hi", "hello", "hey", "start", "hie", "yo"):
            logger.info(f"[ROUTE] customer={customer_id} path=GREETING input={lower!r}")
            return [_text(self.WELCOME)]

        # ── 9. Explicit commands ──
        if lower in ("find", "find medicine", "search", "1️⃣"):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_FIND")
            return [_text(self.SEARCH_PROMPT)]
        if lower in ("near me", "nearby", "2️⃣", "pharmacies near me"):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_NEARBY")
            return [_text(self.NEAR_ME_PROMPT)]
        if lower in ("saved", "my saved", "3️⃣", "my saved pharmacies"):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_SAVED")
            return await self._show_saved_pharmacies(customer_id)
        if lower in ("save",):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_SAVE")
            return await self._save_current_pharmacy(customer_id, session)
        if lower in ("rate",):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_RATE")
            return await self._show_rating_prompt(customer_id, session)
        if lower in ("pro", "upgrade", "subscribe", "pro mode"):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_PRO")
            return await self._handle_pro_info(customer_id)
        if lower.startswith("pay ") or lower.startswith("activate pro"):
            logger.info(f"[ROUTE] customer={customer_id} path=CMD_PAY input={text[:80]!r}")
            return await self._handle_pro_payment(customer_id, text)

        # ── 10. Rate N [comment] ──
        if lower.startswith("rate "):
            logger.info(f"[ROUTE] customer={customer_id} path=RATE_CMD input={text!r}")
            return await self._handle_rate_command(customer_id, text, session)

        # ── 11. Pharmacy search: "pharmacy Avondale" or just "pharmacy" ──
        if lower == "pharmacy" or lower.startswith("pharmacy "):
            query = text[len("pharmacy"):].strip()
            logger.info(f"[ROUTE] customer={customer_id} path=PHARMACY_SEARCH query={query!r}")
            return await self._search_pharmacies(customer_id, query)
        if lower.startswith("find pharmacy"):
            query = text[len("find pharmacy"):].strip()
            logger.info(f"[ROUTE] customer={customer_id} path=PHARMACY_SEARCH query={query!r}")
            return await self._search_pharmacies(customer_id, query)

        # ── 12. Medication reminders ──
        if lower.startswith("remind ") or lower.startswith("reminder "):
            logger.info(f"[ROUTE] customer={customer_id} path=REMINDER_SET input={text[:80]!r}")
            return await self._handle_set_reminder(customer_id, text)
        if lower in ("reminders", "my reminders", "list reminders"):
            logger.info(f"[ROUTE] customer={customer_id} path=REMINDER_LIST")
            return await self._handle_list_reminders(customer_id)
        if lower.startswith("cancel reminder") or lower == "cancel all reminders":
            logger.info(f"[ROUTE] customer={customer_id} path=REMINDER_CANCEL input={text[:80]!r}")
            return await self._handle_cancel_reminder(customer_id, text)

        # ── 13. Symptom detection → LLM → medicine search ──
        if _is_symptom_text(text):
            logger.info(f"[ROUTE] customer={customer_id} path=SYMPTOM_LLM text={text[:80]!r}")
            return await self._handle_symptoms(customer_id, text)

        # ── 13. Default: treat as medicine name search ──
        logger.info(f"[ROUTE] customer={customer_id} path=MEDICINE_SEARCH text={text[:80]!r}")
        return await self._search_medicines(customer_id, [text], text)

    # ═══════════════════════════════════════════════════════════════════════
    # Handlers
    # ═══════════════════════════════════════════════════════════════════════

    async def _handle_image(self, customer_id: str, media_url: str) -> List[dict]:
        """OCR → LLM extract medicines → search."""
        try:
            raw_text = ocr_service.extract_text_from_url(media_url)
            logger.info(f"[OCR] customer={customer_id} text={raw_text[:300]!r}")

            if not raw_text.strip():
                return [_text(
                    "📸 I received your image but couldn't read any text.\n\n"
                    "Please type the medicine names instead.\n\n"
                    "_Reply *0* for main menu_"
                )]

            # LLM: extract medicine names from OCR text
            parsed = stepfun_service.extract_medicines_from_ocr_text(raw_text)
            medicines = [m["name"] if isinstance(m, dict) else str(m) for m in parsed if m]
            logger.info(f"[OCR→LLM] customer={customer_id} medicines={medicines}")

            if not medicines:
                # Fallback: try extract_medicines_from_text (simpler prompt)
                medicines = stepfun_service.extract_medicines_from_text(raw_text)
                logger.info(f"[OCR→LLM fallback] medicines={medicines}")

            if not medicines:
                return [_text(
                    "📸 I scanned your image but couldn't identify specific medicines.\n\n"
                    "Please type the medicine names manually.\n\n"
                    "_Reply *0* for main menu_"
                )]

            # Search
            names_str = ", ".join(f"*{m}*" for m in medicines[:5])
            search_results = await self._search_medicines(customer_id, medicines[:5], "[prescription scan]")
            return [_text(f"📸 Found from your image: {names_str}\n\nSearching...")] + search_results

        except Exception as e:
            logger.error(f"Image processing error for {customer_id}: {e}", exc_info=True)
            return [_text(
                "📸 Sorry, I had trouble reading that image.\n\n"
                "Please type the medicine names instead.\n\n"
                "_Reply *0* for main menu_"
            )]

    async def _handle_location(self, customer_id: str, coords: Tuple[float, float]) -> List[dict]:
        """User shared a location — search open pharmacies sorted by distance."""
        lat, lng = coords
        logger.info(f"[LOCATION] customer={customer_id} lat={lat} lng={lng}")

        # Save coords on the customer record for distance sorting
        try:
            await db.update_customer(customer_id, {"latitude": lat, "longitude": lng})
        except Exception as e:
            logger.warning(f"Failed to save customer location: {e}")

        # Get ALL active pharmacies, compute distance, filter open, sort
        results = await db.search_pharmacies_by_area("")
        if not results:
            return [_text(
                "📍 Got your location! But I couldn't find pharmacies nearby.\n\n"
                "Try typing *pharmacy [area name]* instead.\n\n"
                "_Reply *0* for main menu_"
            )]

        # Compute distance and open status for each pharmacy
        enriched = []
        for p in results:
            p_lat = p.get("latitude")
            p_lng = p.get("longitude")
            if p_lat and p_lng:
                try:
                    p["distance_km"] = round(_haversine(lat, lng, float(p_lat), float(p_lng)), 2)
                except (ValueError, TypeError):
                    p["distance_km"] = None
            else:
                p["distance_km"] = None
            hours_data = _parse_opening_hours(p.get("opening_hours"))
            p["_is_open"] = _is_pharmacy_open(hours_data)
            enriched.append(p)

        # Sort: open first, then by distance
        enriched.sort(key=lambda p: (
            0 if p["_is_open"] is True else (2 if p["_is_open"] is False else 1),
            p.get("distance_km") if p.get("distance_km") is not None else 9999,
        ))

        return await self._format_pharmacy_results(
            customer_id, enriched[:8], "your location 📍", user_coords=coords
        )

    # ── Medication reminder handlers ─────────────────────────────────────

    _REMIND_RE = re.compile(
        r"^remind(?:er)?\s+(.+?)\s+(?:at\s+)?(\d{1,2}[:\.]?\d{0,2})\s*(am|pm)?",
        re.IGNORECASE,
    )

    async def _handle_set_reminder(self, customer_id: str, text: str) -> List[dict]:
        """Parse 'remind Paracetamol 08:00' or 'remind Metformin 2pm' and create a reminder."""
        m = self._REMIND_RE.match(text)
        if not m:
            return [_text(
                "⏰ *Set a medication reminder*\n\n"
                "Format: *remind [medicine] [time]*\n"
                "Examples:\n"
                "  _remind Paracetamol 08:00_\n"
                "  _remind Metformin 2pm_\n"
                "  _remind Blood pressure pill 9:30am_\n\n"
                "_Reply *reminders* to see your list_\n"
                "_Reply *0* for main menu_"
            )]

        medicine_name = m.group(1).strip()
        raw_time = m.group(2).replace(".", ":")
        ampm = (m.group(3) or "").lower()

        # Parse time
        try:
            if ":" in raw_time:
                parts = raw_time.split(":")
                hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            else:
                hour, minute = int(raw_time), 0
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time")
            time_str = f"{hour:02d}:{minute:02d}:00"
        except (ValueError, IndexError):
            return [_text("⚠️ Invalid time format. Try: *remind Paracetamol 08:00* or *remind Metformin 2pm*")]

        try:
            await db.create_reminder({
                "customer_id": customer_id,
                "medicine_name": medicine_name,
                "reminder_time": time_str,
            })
            display_time = f"{hour:02d}:{minute:02d}"
            return [_text(
                f"✅ Reminder set!\n\n"
                f"💊 *{medicine_name}*\n"
                f"⏰ Every day at *{display_time} CAT*\n\n"
                "_All times are Central Africa Time (UTC+2)_\n\n"
                "_Reply *reminders* to see all your reminders_\n"
                "_Reply *0* for main menu_"
            )]
        except Exception as e:
            logger.error(f"Failed to create reminder for {customer_id}: {e}")
            return [_text("⚠️ Sorry, I couldn't save that reminder. Please try again.")]

    async def _handle_list_reminders(self, customer_id: str) -> List[dict]:
        """Show all active reminders for this customer."""
        try:
            reminders = await db.list_reminders(customer_id)
        except Exception as e:
            logger.error(f"Failed to list reminders for {customer_id}: {e}")
            return [_text("⚠️ Sorry, I couldn't load your reminders right now.")]

        if not reminders:
            return [_text(
                "⏰ *Your Medication Reminders*\n\n"
                "You don't have any active reminders.\n\n"
                "Set one with: *remind [medicine] [time]*\n"
                "Example: _remind Paracetamol 08:00_\n\n"
                "_Reply *0* for main menu_"
            )]

        lines = ["⏰ *Your Medication Reminders*\n"]
        for idx, r in enumerate(reminders, 1):
            t = r.get("reminder_time", "?")
            if isinstance(t, str) and len(t) >= 5:
                t = t[:5]  # "08:00:00" → "08:00"
            lines.append(f"{idx}. 💊 *{r.get('medicine_name', '?')}* — {t} CAT")
        lines.append("")
        lines.append("_All times are Central Africa Time (UTC+2)_")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Cancel one: *cancel reminder [number]*_")
        lines.append("_Cancel all: *cancel all reminders*_")
        lines.append("_Reply *0* for main menu_")
        return [_text("\n".join(lines))]

    async def _handle_cancel_reminder(self, customer_id: str, text: str) -> List[dict]:
        """Cancel one or all reminders."""
        lower = text.strip().lower()

        if lower == "cancel all reminders":
            try:
                count = await db.cancel_all_reminders(customer_id)
                if count == 0:
                    return [_text("You don't have any active reminders to cancel.\n\n_Reply *0* for main menu_")]
                return [_text(f"✅ Cancelled {count} reminder{'s' if count != 1 else ''}.\n\n_Reply *0* for main menu_")]
            except Exception as e:
                logger.error(f"Failed to cancel all reminders for {customer_id}: {e}")
                return [_text("⚠️ Sorry, couldn't cancel reminders. Please try again.")]

        # "cancel reminder 2" → cancel the 2nd reminder
        num_match = re.search(r"(\d+)", lower)
        if not num_match:
            return [_text(
                "To cancel a reminder, type:\n"
                "  *cancel reminder [number]*\n"
                "  *cancel all reminders*\n\n"
                "_Reply *reminders* to see your list_"
            )]

        idx = int(num_match.group(1))
        try:
            reminders = await db.list_reminders(customer_id)
            if not reminders or idx < 1 or idx > len(reminders):
                return [_text(f"⚠️ No reminder #{idx}. Reply *reminders* to see your list.")]
            target = reminders[idx - 1]
            await db.cancel_reminder(target["id"], customer_id)
            return [_text(
                f"✅ Cancelled reminder for *{target.get('medicine_name', '?')}*.\n\n"
                "_Reply *reminders* to see remaining_\n"
                "_Reply *0* for main menu_"
            )]
        except Exception as e:
            logger.error(f"Failed to cancel reminder for {customer_id}: {e}")
            return [_text("⚠️ Sorry, couldn't cancel that reminder. Please try again.")]

    # ── Pro Mode handlers ─────────────────────────────────────────────────

    async def _handle_pro_info(self, customer_id: str) -> List[dict]:
        """Show Pro Mode subscription info."""
        # Check if user already has an active subscription
        try:
            customer = await db.get_customer_by_id(customer_id)
            is_pro = customer.get("is_pro", False) if customer else False
        except Exception:
            is_pro = False

        if is_pro:
            return [_text(
                "⭐ *RERUN Health Pro — Active*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Your Pro subscription is active! You have access to:\n\n"
                "🤖 *AI Chat Mode* — natural conversation instead of menu commands\n"
                "⏰ *Smart Reminders* — intelligent medication scheduling\n"
                "📊 *Health Insights* — personalized medicine recommendations\n"
                "🔔 *Priority Support* — faster pharmacy responses\n\n"
                "_Reply *0* for main menu_"
            )]

        return [_text(
            "⭐ *RERUN Health Pro*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Upgrade to Pro for *$2.99/month* and unlock:\n\n"
            "🤖 *AI Chat Mode* — talk naturally instead of using menu commands\n"
            "⏰ *Smart Reminders* — intelligent medication scheduling\n"
            "📊 *Health Insights* — personalized medicine recommendations\n"
            "🔔 *Priority Support* — faster pharmacy responses\n\n"
            "💳 *Pay via EcoCash:*\n"
            "Type: *pay 0786280681*\n"
            "or: *activate pro*\n\n"
            "_Reply *0* for main menu_"
        )]

    async def _handle_pro_payment(self, customer_id: str, text: str) -> List[dict]:
        """Handle Pro Mode payment via EcoCash (dummy implementation)."""
        # Extract phone number if provided: "pay 077..." or "activate pro"
        phone_match = re.search(r"(07\d{8})", text)
        payer_phone = phone_match.group(1) if phone_match else None

        logger.info(f"[PRO_PAYMENT] customer={customer_id} payer_phone={payer_phone}")

        # ── DUMMY IMPLEMENTATION ──
        # In production, this would:
        # 1. Call EcoCash API: POST https://developers.ecocash.co.zw/api/transactions
        #    with merchant_number=0786280681, amount=2.99, currency=USD,
        #    payer_msisdn=payer_phone
        # 2. Poll for transaction status
        # 3. On success, update customer record with is_pro=True, pro_expires_at=now+30d
        # 4. Send confirmation message

        # For now, simulate a successful payment
        try:
            pro_expires = datetime.now(timezone.utc) + timedelta(days=30)
            await db.update_customer(customer_id, {
                "is_pro": True,
                "pro_expires_at": pro_expires.isoformat(),
            })
            return [_text(
                "✅ *Pro Mode Activated!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🎉 Welcome to RERUN Health Pro!\n\n"
                "Your subscription is active until "
                f"*{pro_expires.strftime('%d %B %Y')}*.\n\n"
                "🤖 *AI Chat Mode* is now enabled — just type naturally!\n"
                "⏰ *Smart Reminders* — set reminders with _remind [medicine] [time]_\n\n"
                f"💳 EcoCash payment of $2.99 to 0786280681"
                f"{' from ' + payer_phone if payer_phone else ''} (simulated)\n\n"
                "_Reply *0* for main menu_"
            )]
        except Exception as e:
            logger.error(f"[PRO_PAYMENT] Failed for {customer_id}: {e}")
            return [_text(
                "⚠️ Sorry, there was a problem processing your payment.\n\n"
                "Please try again or contact support.\n\n"
                "_Reply *0* for main menu_"
            )]

    # Common symptom → OTC suggestion map (shown before searching)
    _SYMPTOM_SUGGESTIONS: dict = {
        "headache":     ("headache / mild pain",   ["Paracetamol", "Ibuprofen", "Aspirin"]),
        "pain":         ("pain relief",             ["Paracetamol", "Ibuprofen", "Diclofenac"]),
        "fever":        ("fever",                   ["Paracetamol", "Ibuprofen"]),
        "cold":         ("cold & flu",              ["Flu medication", "Paracetamol", "Vitamin C"]),
        "flu":          ("cold & flu",              ["Flu medication", "Paracetamol", "Vitamin C"]),
        "cough":        ("cough",                   ["Cough syrup", "Bromhexine", "Honey & Lemon"]),
        "sore throat":  ("sore throat",             ["Strepsils", "Benzocaine lozenges", "Ibuprofen"]),
        "allerg":       ("allergies",               ["Cetirizine", "Loratadine", "Chlorphenamine"]),
        "stomach":      ("stomach / indigestion",   ["Omeprazole", "Antacid", "Buscopan"]),
        "nausea":       ("nausea / vomiting",       ["Metoclopramide", "Domperidone", "Ginger tablets"]),
        "vomit":        ("nausea / vomiting",       ["Metoclopramide", "Domperidone"]),
        "diarrhea":     ("diarrhoea",               ["ORS sachets", "Loperamide", "Zinc tablets"]),
        "heartburn":    ("heartburn / acid reflux", ["Omeprazole", "Antacid", "Ranitidine"]),
        "rash":         ("skin rash / itch",        ["Hydrocortisone cream", "Cetirizine", "Calamine lotion"]),
        "itch":         ("skin itch",               ["Hydrocortisone cream", "Cetirizine", "Calamine lotion"]),
        "infection":    ("infection",               ["Amoxicillin", "Metronidazole", "Flucloxacillin"]),
        "toothache":    ("toothache",               ["Ibuprofen", "Paracetamol", "Clove oil"]),
        "earache":      ("earache",                 ["Ibuprofen", "Paracetamol", "Ear drops"]),
        "back pain":    ("back pain",               ["Ibuprofen", "Diclofenac gel", "Muscle relaxant"]),
        "chest pain":   ("chest discomfort",        ["Antacid", "Ibuprofen"]),
        "cramp":        ("cramps",                  ["Buscopan", "Ibuprofen", "Magnesium"]),
        "runny nose":   ("runny / blocked nose",    ["Pseudoephedrine", "Saline nasal spray", "Cetirizine"]),
        "blocked nose": ("runny / blocked nose",    ["Pseudoephedrine", "Saline nasal spray", "Xylometazoline"]),
        "dizzy":        ("dizziness",               ["Stugeron", "Betahistine"]),
        "swelling":     ("swelling / inflammation", ["Ibuprofen", "Diclofenac", "Compression bandage"]),
    }

    def _get_symptom_suggestion(self, text: str) -> Optional[Tuple[str, List[str]]]:
        """Return (label, [medicine names]) for the best matching symptom keyword, or None."""
        lower = text.lower()
        for kw, (label, meds) in self._SYMPTOM_SUGGESTIONS.items():
            if kw in lower:
                return label, meds
        return None

    async def _handle_symptoms(self, customer_id: str, text: str) -> List[dict]:
        """Use LLM to extract medicine names from symptom description, then search."""
        # Build a friendly suggestion header before searching
        suggestion = self._get_symptom_suggestion(text)
        try:
            medicines = stepfun_service.extract_medicines_from_text(text)
            logger.info(f"[SYMPTOMS→LLM] customer={customer_id} text={text!r} medicines={medicines}")

            if medicines:
                results = await self._search_medicines(customer_id, medicines, text)
                # Prepend a suggestion note with disclaimer as first message
                if suggestion:
                    label, suggested = suggestion
                    meds_str = ", ".join(f"*{m}*" for m in suggested)
                    note = (
                        f"🤒 Common OTC options for *{label}*:\n"
                        f"{meds_str}\n\n"
                        f"_⚕️ Please consult your pharmacist before taking any medication._"
                    )
                    return [_text(note)] + results
                return results
        except Exception as e:
            logger.error(f"Symptom LLM error: {e}")

        # Fallback: tell user we couldn't understand
        return [_text(
            "🤔 I understand you're not feeling well.\n\n"
            "Could you tell me the *medicine name* you're looking for?\n"
            "Or try describing your symptoms differently.\n\n"
            "_e.g. paracetamol, ibuprofen, flu medicine_\n"
            "_Reply *0* for main menu_"
        )]

    async def _handle_rate_command(self, customer_id: str, text: str, session: dict) -> List[dict]:
        """Handle 'rate 4' or 'rate 5 great service'."""
        pharmacy_id = session.get("viewing_pharmacy")
        if not pharmacy_id:
            return [_text("Please view a pharmacy first, then type *rate 1-5*.\n\n_Reply *0* for main menu_")]

        parts = text.split(None, 2)
        try:
            score = int(parts[1])
            if not (1 <= score <= 5):
                raise ValueError
        except (IndexError, ValueError):
            return await self._show_rating_prompt(customer_id, session)

        comment = parts[2] if len(parts) > 2 else None

        if comment:
            return await self._finalize_rating(customer_id, score, comment, pharmacy_id)

        # Prompt for optional comment
        await _save_session(customer_id, {"awaiting_comment": {"score": score, "pharmacy_id": pharmacy_id}})
        return [_text(f"{_stars(score)} Got it!\n\nWant to leave a comment? Type it now, or reply *skip*.")]

    async def _finalize_rating(self, customer_id: str, score: int, comment: Optional[str], pharmacy_id: str) -> List[dict]:
        await db.create_or_update_rating({
            "customer_id": customer_id,
            "pharmacy_id": pharmacy_id,
            "score": score,
            "comment": comment,
        })
        # Clear awaiting_comment from session so next message isn't captured
        await _save_session(customer_id, {"awaiting_comment": None})
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        name = pharmacy.get("name", "the pharmacy") if pharmacy else "the pharmacy"
        msg = f"✅ You rated *{name}* {_stars(score)}"
        if comment:
            msg += f"\n_{comment}_"
        msg += "\n\nThank you! 🙏\n\n_Type a medicine name to search, or *0* for menu_"
        return [_text(msg)]

    async def _show_rating_prompt(self, customer_id: str, session: dict) -> List[dict]:
        pharmacy_id = session.get("viewing_pharmacy")
        if not pharmacy_id:
            return [_text("Please view a pharmacy first, then type *rate*.\n\n_Reply *0* for main menu_")]
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        name = pharmacy.get("name", "this pharmacy") if pharmacy else "this pharmacy"
        return [_text(
            f"⭐ *Rate {name}*\n\n"
            "Reply with *rate 1* to *rate 5*:\n"
            "  1 = Poor · 2 = Fair · 3 = OK · 4 = Good · 5 = Excellent\n\n"
            "_e.g. rate 5 great service!_\n"
            "_Reply *0* for main menu_"
        )]

    async def _save_current_pharmacy(self, customer_id: str, session: dict) -> List[dict]:
        pharmacy_id = session.get("viewing_pharmacy")
        if not pharmacy_id:
            return [_text("Please view a pharmacy first, then type *save*.\n\n_Reply *0* for main menu_")]
        try:
            await db.save_pharmacy_for_customer(customer_id, pharmacy_id)
            pharmacy = await db.get_pharmacy_details(pharmacy_id)
            name = pharmacy.get("name", "Pharmacy") if pharmacy else "Pharmacy"
            return [_text(f"💾 *{name}* saved!\n\nType *saved* to see all your bookmarks.\n_Reply *0* for main menu_")]
        except Exception as e:
            logger.error(f"Save pharmacy error: {e}")
            return [_text("⚠️ Couldn't save. Please try again.\n\n_Reply *0* for main menu_")]

    async def _show_saved_pharmacies(self, customer_id: str) -> List[dict]:
        try:
            saved = await db.get_saved_pharmacies(customer_id)
        except Exception as e:
            logger.error(f"Saved pharmacies fetch error: {e}")
            saved = []

        if not saved:
            return [_text(
                "💾 *My Saved Pharmacies*\n\n"
                "You haven't saved any yet.\n"
                "View a pharmacy and type *save* to bookmark it.\n\n"
                "_Reply *0* for main menu_"
            )]

        lines = ["💾 *My Saved Pharmacies*\n"]
        pharmacy_ids = []
        for idx, row in enumerate(saved[:10], 1):
            p = row.get("pharmacies") or {}
            if not p.get("id"):
                continue
            pharmacy_ids.append(p["id"])
            hours_data = _parse_opening_hours(p.get("opening_hours"))
            status = _open_status_badge(hours_data)
            line = f"{idx}. {status} *{p.get('name', '?')}*" if status else f"{idx}. *{p.get('name', '?')}*"
            suburb = p.get("suburb") or p.get("city") or ""
            if suburb:
                line += f"\n   📍 {suburb}"
            lines.append(line)
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Reply with a number for details_")
        lines.append("_Reply *0* for main menu_")

        await _save_session(customer_id, {"search_results": pharmacy_ids})
        return [_text("\n".join(lines))]

    async def _show_pharmacy_detail(self, customer_id: str, pharmacy_id: str) -> List[dict]:
        """Show full pharmacy detail as a single text message with Maps link."""
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        if not pharmacy:
            return [_text("Sorry, that pharmacy is no longer available.\n\n_Reply *0* for main menu_")]

        await _save_session(customer_id, {"viewing_pharmacy": pharmacy_id})
        return [_text(_fmt_pharmacy_detail(pharmacy))]

    # ═══════════════════════════════════════════════════════════════════════
    # Search & format
    # ═══════════════════════════════════════════════════════════════════════

    async def _search_medicines(self, customer_id: str, names: List[str], query: str) -> List[dict]:
        """Search medicines by name, format as a single numbered list grouped by pharmacy."""
        results = await search_service.find_medicines(names)
        await analytics_service.log_search(customer_id, query, results)

        if not results or all(not r.get("pharmacies") for r in results):
            # Auto-add for admin review
            for name in names:
                await db.add_unverified_medicine(name.strip(), added_by=customer_id)
            names_str = ", ".join(f"*{n}*" for n in names)
            return [_text(
                f"😔 No pharmacies found with {names_str} in stock.\n\n"
                "• Try a different spelling or generic name\n"
                "• Describe your symptoms instead\n"
                "• Send a prescription photo 📸\n\n"
                "_Reply *0* for main menu_"
            )]

        # Build a flat list: group inventory by pharmacy across all medicines
        # pharmacy_id → {pharmacy_data, medicines: [{name, price, in_stock, qty}]}
        pharmacy_map = {}
        for med in results:
            med_name = med.get("name", "Unknown")
            for inv in med.get("pharmacies", []):
                p = inv.get("pharmacies") or {}
                p_id = p.get("id") or inv.get("pharmacy_id")
                if not p_id:
                    continue
                if p_id not in pharmacy_map:
                    pharmacy_map[p_id] = {"pharmacy": p, "medicines": [], "best_price": 9999, "is_open": None}
                pharmacy_map[p_id]["medicines"].append({
                    "name": med_name,
                    "price": inv.get("price"),
                    "in_stock": inv.get("in_stock", True),
                    "quantity_available": inv.get("quantity_available"),
                })
                try:
                    price = float(inv.get("price", 9999))
                except (ValueError, TypeError):
                    price = 9999
                if price < pharmacy_map[p_id]["best_price"]:
                    pharmacy_map[p_id]["best_price"] = price

                # Compute open status once
                if pharmacy_map[p_id]["is_open"] is None:
                    hours_data = _parse_opening_hours(p.get("opening_hours"))
                    pharmacy_map[p_id]["is_open"] = _is_pharmacy_open(hours_data)

        # Sort: open first, then by best price
        sorted_entries = sorted(
            pharmacy_map.values(),
            key=lambda e: (0 if e["is_open"] is True else (2 if e["is_open"] is False else 1), e["best_price"]),
        )

        # Format
        lines = []
        searched_names = ", ".join(f"*{n}*" for n in names)
        lines.append(f"💊 Results for {searched_names}:\n")

        pharmacy_ids = []
        for idx, entry in enumerate(sorted_entries[:8], 1):
            p = entry["pharmacy"]
            pharmacy_ids.append(p.get("id") or "")
            lines.append(_fmt_pharmacy_line(idx, p, medicines_info=entry["medicines"]))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Reply with a *number* for full details_")
        lines.append("_Type another medicine name to search_")
        lines.append("_Reply *0* for main menu_")

        await _save_session(customer_id, {"search_results": pharmacy_ids})
        return [_text("\n".join(lines))]

    async def _search_pharmacies(self, customer_id: str, query: str) -> List[dict]:
        """Search pharmacies by name or area."""
        if not query:
            return [_text(self.NEAR_ME_PROMPT)]

        results = await db.search_pharmacies_by_name(query)
        if not results:
            results = await db.search_pharmacies_by_area(query)

        if not results:
            return [_text(
                f"😔 No pharmacies found for *{query}*.\n\n"
                "Try a different area name or spelling.\n\n"
                "_Reply *0* for main menu_"
            )]

        return await self._format_pharmacy_results(customer_id, results[:5], query)

    async def _format_pharmacy_results(
        self,
        customer_id: str,
        results: list,
        label: str,
        user_coords: Optional[Tuple[float, float]] = None,
    ) -> List[dict]:
        """Format a pharmacy list as a single text message and save IDs for selection."""
        lines = [f"🏥 Pharmacies near *{label}*:\n"]
        pharmacy_ids = []
        for idx, p in enumerate(results, 1):
            pharmacy_ids.append(p["id"])
            hours_data = _parse_opening_hours(p.get("opening_hours"))
            status = _open_status_badge(hours_data)
            header = f"{idx}. {status} *{p.get('name', '?')}*" if status else f"{idx}. *{p.get('name', '?')}*"
            lines.append(header)
            loc = ", ".join(filter(None, [p.get("address", ""), p.get("suburb", "")]))
            if loc:
                lines.append(f"   📍 {loc}")
            # Distance line (from user location or pre-computed)
            dist = p.get("distance_km")
            if dist is None and user_coords:
                p_lat, p_lng = p.get("latitude"), p.get("longitude")
                if p_lat and p_lng:
                    try:
                        dist = round(_haversine(user_coords[0], user_coords[1], float(p_lat), float(p_lng)), 2)
                    except (ValueError, TypeError):
                        pass
            if dist is not None:
                lines.append(f"   📏 {dist:.2f} km away")
            phone = p.get("phone") or p.get("whatsapp_number")
            if phone:
                lines.append(f"   📞 {phone}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Reply with a *number* for full details_")
        lines.append("_Reply *0* for main menu_")

        await _save_session(customer_id, {"search_results": pharmacy_ids})
        return [_text("\n".join(lines))]


whatsapp_service = WhatsAppService()
