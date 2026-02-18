"""
WhatsApp conversation orchestrator.

Manages the full customer conversation flow with interactive messages:
  - Welcome message + Quick Reply buttons
  - Medicine search (ranked by: open now → price → distance → stock)
  - Pharmacy search (by name / area)
  - Pharmacy details with location card + CTA buttons
  - Rating flow with quick reply buttons
  - Prescription image handling
  - Menu / help

Response format: Each handler returns a list of message actions:
  [{"type": "text", "body": "..."}, {"type": "interactive", "template": "welcome"}, ...]
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from loguru import logger

from app import database as db
from app.services.stepfun_service import stepfun_service
from app.services.search_service import search_service
from app.services.analytics_service import analytics_service
from app.services.ocr_service import ocr_service

# Zimbabwe is CAT (UTC+2)
CAT = timezone(timedelta(hours=2))

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ── Response builder helpers ─────────────────────────────────────────────

def _text(body: str) -> dict:
    """Plain text message action."""
    return {"type": "text", "body": body}

def _interactive(template: str) -> dict:
    """Interactive template message action (quick-reply buttons)."""
    return {"type": "interactive", "template": template}

def _location(lat: float, lng: float, label: str, address: str = "") -> dict:
    """Location message action."""
    return {"type": "location", "lat": lat, "lng": lng, "label": label, "address": address}

def _stars(score: int) -> str:
    """Return star emoji string for a rating score."""
    return "⭐" * score


# ── Opening hours helpers ─────────────────────────────────────────────────

def _parse_opening_hours(raw) -> Optional[dict]:
    """Parse opening_hours from JSONB (dict or JSON string) to a WeekSchedule dict."""
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
    """Check if pharmacy is currently open based on CAT time."""
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
    """Convert 24h time string to 12h format."""
    try:
        h, m = t.split(":")
        hour = int(h)
        ampm = "PM" if hour >= 12 else "AM"
        h12 = 12 if hour == 0 else (hour - 12 if hour > 12 else hour)
        return f"{h12}:{m}{ampm}"
    except Exception:
        return t


def _fmt_opening_hours_short(hours_data: Optional[dict]) -> str:
    """Format opening hours as a compact string for WhatsApp."""
    if not hours_data:
        return ""
    groups = []
    closed_days = []
    for day_key, idx in DAY_MAP.items():
        d = hours_data.get(day_key, {})
        if not d.get("open"):
            closed_days.append(DAY_LABELS[idx])
            continue
        frm, to = d.get("from", "08:00"), d.get("to", "17:00")
        last = groups[-1] if groups else None
        if last and last["from"] == frm and last["to"] == to:
            last["days"].append(DAY_LABELS[idx])
        else:
            groups.append({"days": [DAY_LABELS[idx]], "from": frm, "to": to})

    parts = []
    for g in groups:
        day_range = f"{g['days'][0]}-{g['days'][-1]}" if len(g["days"]) > 2 else ", ".join(g["days"])
        parts.append(f"{day_range}: {_fmt_time_12h(g['from'])}-{_fmt_time_12h(g['to'])}")
    if closed_days:
        cd = f"{closed_days[0]}-{closed_days[-1]}" if len(closed_days) > 2 else ", ".join(closed_days)
        parts.append(f"{cd}: Closed")
    return " | ".join(parts)


def _fmt_opening_hours_detail(hours_data: Optional[dict]) -> str:
    """Format opening hours line-by-line for pharmacy detail view."""
    if not hours_data:
        return ""
    lines = []
    for day_key, idx in DAY_MAP.items():
        d = hours_data.get(day_key, {})
        label = DAY_LABELS[idx]
        if d.get("open"):
            lines.append(f"  {label}  {_fmt_time_12h(d.get('from', '08:00'))} - {_fmt_time_12h(d.get('to', '17:00'))}")
        else:
            lines.append(f"  {label}  Closed")
    return "\n".join(lines)


def _open_status_badge(hours_data: Optional[dict]) -> str:
    """Return open/closed badge."""
    is_open = _is_pharmacy_open(hours_data)
    if is_open is True:
        return "🟢 Open Now"
    elif is_open is False:
        # Find next opening time
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
    """Return stock status badge."""
    if not in_stock:
        return "❌ Out of Stock"
    try:
        q = int(qty) if qty else None
    except (ValueError, TypeError):
        q = None
    if q is not None and q <= 5:
        return f"⚠️ Limited Stock ({q} left)"
    if q is not None:
        return f"✅ In Stock ({q}+ available)"
    return "✅ In Stock"


def _payment_icons(p: dict) -> str:
    """Build payment method icons from pharmacy data."""
    methods = []
    methods.append("💵 Cash")
    if p.get("accepts_medical_aid"):
        methods.append("💳 Medical Aid")
    if p.get("has_delivery"):
        methods.append("🚚 Delivery")
    return ", ".join(methods) if methods else ""


# ── Ranking helper ────────────────────────────────────────────────────────

def _rank_pharmacy_results(results: list) -> list:
    """
    Rank pharmacies by priority:
    1. Open Now (open first, closed last)
    2. Price (lowest first)
    3. Distance (if available)
    4. Stock availability (in-stock first, limited next, out-of-stock last)
    """
    def sort_key(inv):
        p = inv.get("pharmacies") or inv
        hours_data = _parse_opening_hours(p.get("opening_hours"))
        is_open = _is_pharmacy_open(hours_data)

        # Priority 1: Open status (True=0, None=1, False=2)
        open_score = 0 if is_open is True else (2 if is_open is False else 1)

        # Priority 2: Price
        try:
            price = float(inv.get("price", 9999))
        except (ValueError, TypeError):
            price = 9999

        # Priority 3: Distance
        dist = p.get("distance_km") or 999

        # Priority 4: Stock
        in_stock = inv.get("in_stock", True)
        try:
            qty = int(inv.get("quantity_available", 0) or 0)
        except (ValueError, TypeError):
            qty = 0
        stock_score = 0 if (in_stock and qty > 5) else (1 if in_stock else 2)

        return (open_score, price, dist, stock_score)

    return sorted(results, key=sort_key)


# ── Message formatting ────────────────────────────────────────────────────

def _fmt_pharmacy_line(idx: int, p: dict, inv: dict = None) -> str:
    """Format a single pharmacy result line — professional WhatsApp layout."""
    hours_data = _parse_opening_hours(p.get("opening_hours"))
    status = _open_status_badge(hours_data)

    lines = [f"{idx}. {status} *{p.get('name', 'Unknown')}*" if status else f"{idx}. *{p.get('name', 'Unknown')}*"]

    details = []
    if inv:
        price = inv.get("price", "—")
        in_stock = inv.get("in_stock", True)
        qty = inv.get("quantity_available", "")
        details.append(f"� ${price}")
        details.append(_stock_badge(in_stock, qty))
    if details:
        lines.append(f"   {' | '.join(details)}")

    # Location
    loc_parts = []
    dist = p.get("distance_km")
    if dist is not None:
        loc_parts.append(f"{dist} km away")
    addr = p.get("address", "")
    suburb = p.get("suburb", "")
    loc_str = ", ".join(filter(None, [addr, suburb]))
    if loc_str:
        loc_parts.append(loc_str)
    if loc_parts:
        lines.append(f"   📍 {' · '.join(loc_parts)}")

    # Payment / services
    pay = _payment_icons(p)
    if pay:
        lines.append(f"   {pay}")

    # Phone
    phone = p.get("whatsapp_number") or p.get("phone")
    if phone:
        lines.append(f"   📞 {phone}")

    return "\n".join(lines)


def _fmt_pharmacy_detail(p: dict) -> str:
    """Format a full pharmacy detail card — clean professional layout."""
    hours_data = _parse_opening_hours(p.get("opening_hours"))
    status = _open_status_badge(hours_data)

    lines = [f"🏥 *{p.get('name', 'Unknown')}*"]
    if status:
        lines.append(status)
    lines.append("")

    # Rating
    rating = p.get("rating")
    if rating:
        full = int(float(rating))
        stars = "⭐" * full
        lines.append(f"{stars} {rating}/5 ({p.get('total_reviews', 0)} reviews)")
        lines.append("")

    # Contact
    lines.append("*Contact*")
    loc = ", ".join(filter(None, [p.get("address", ""), p.get("suburb", ""), p.get("city", "")]))
    if loc:
        lines.append(f"📍 {loc}")
    phone = p.get("phone")
    if phone:
        lines.append(f"📞 {phone}")
    wa = p.get("whatsapp_number")
    if wa and wa != phone:
        lines.append(f"💬 {wa}")
    lines.append("")

    # Opening Hours
    if hours_data:
        lines.append("*Opening Hours*")
        lines.append(_fmt_opening_hours_detail(hours_data))
        lines.append("")

    # Services
    services = []
    if p.get("accepts_medical_aid"):
        services.append("💳 Accepts Medical Aid")
    if p.get("has_delivery"):
        services.append("🚚 Delivery Available")
    if p.get("is_24_hours"):
        services.append("🕐 Open 24 Hours")
    if p.get("parking_available"):
        services.append("🅿️ Parking Available")
    special = p.get("special_services")
    if special:
        services.append(f"ℹ️ {special}")
    if services:
        lines.append("*Services*")
        for s in services:
            lines.append(f"  {s}")
        lines.append("")

    website = p.get("website")
    if website:
        lines.append(f"🌐 {website}")
        lines.append("")

    lines.append("_Reply *rate [1-5]* to rate this pharmacy_")
    lines.append("_Reply *menu* to go back_")
    return "\n".join(lines)


def _fmt_medicine_results(medicine_name: str, pharmacies: list) -> str:
    """Format medicine search results — ranked and professional."""
    if not pharmacies:
        return (
            f"� *{medicine_name}*\n"
            "No results found.\n\n"
            "Try a different spelling, the generic name, or describe your symptoms.\n\n"
            "_Reply *menu* for options_"
        )

    ranked = _rank_pharmacy_results(pharmacies)
    count = len(ranked)

    lines = [
        f"💊 Found {count} pharmacy{'ies' if count != 1 else ''} with *{medicine_name}*:",
        "",
    ]
    for idx, inv in enumerate(ranked[:5], 1):
        p = inv.get("pharmacies") or inv
        lines.append(_fmt_pharmacy_line(idx, p, inv=inv))
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("Reply with a *number* for full details")
    lines.append("Send another medicine name to search")
    lines.append("_*menu* for all options_")
    return "\n".join(lines)


class WhatsAppService:
    """Orchestrates the WhatsApp conversation flow with interactive messages."""

    async def process_message(
        self,
        customer_id: str,
        message: str,
        media_url: Optional[str] = None,
        history: Optional[List[dict]] = None,
    ) -> List[dict]:
        """Main entry point. Returns a list of message actions to send."""

        # ── Prescription image ──
        if media_url:
            return await self._handle_prescription(customer_id, media_url, message)

        text = message.strip()
        lower = text.lower()

        # ── Quick reply button responses (from interactive templates) ──
        if lower in ("find medicine", "💊 find medicine"):
            return [_text("Type a medicine name or describe your symptoms.\n\n_e.g. paracetamol, headache, amoxicillin 500mg_")]
        if lower in ("near me", "📍 near me"):
            return [_text("Type *pharmacy* followed by an area or name.\n\n_e.g. pharmacy Avondale, pharmacy City Pharmacy_")]
        if lower in ("scan rx", "📸 scan rx"):
            return [_text("📸 Send a photo of your prescription and I'll identify the medicines for you.")]
        if lower in ("rate", "⭐ rate"):
            return [_interactive("rating")]

        # ── Direct commands ──
        if lower in ("hi", "hello", "hey", "start"):
            return [_interactive("welcome")]
        if lower in ("menu", "main menu", "🏠 main menu", "📋 menu"):
            return [_interactive("menu")]
        if lower in ("help", "❓ help"):
            return [_interactive("help")]

        # ── Rating quick reply responses ──
        if lower in ("⭐⭐⭐⭐⭐ (5)", "rate_5"):
            return await self._handle_rating(customer_id, "rate 5", history)
        if lower in ("⭐⭐⭐⭐ (4)", "rate_4"):
            return await self._handle_rating(customer_id, "rate 4", history)
        if lower in ("⭐⭐⭐ (3)", "rate_3"):
            return await self._handle_rating(customer_id, "rate 3", history)

        # ── Rating (typed) ──
        if lower.startswith("rate "):
            return await self._handle_rating(customer_id, text, history)

        # ── Numeric selection (picking from results) ──
        if lower.isdigit():
            return await self._handle_selection(customer_id, int(lower), history)

        # ── Pharmacy search ──
        if lower.startswith("pharmacy ") or lower.startswith("find pharmacy"):
            query = text.split(" ", 1)[1] if " " in text else ""
            return await self._handle_pharmacy_search(customer_id, query.strip())

        # ── New search (quick reply button) ──
        if lower in ("new search", "🔍 new search"):
            return [_text("Type a medicine name or describe your symptoms.\n\n_e.g. paracetamol, headache, amoxicillin 500mg_")]

        # ── Fallback: use AI to understand intent ──
        return await self._handle_ai_intent(customer_id, text, history)

    # ── Handlers ────────────────────────────────────────────────────────────

    async def _handle_prescription(self, customer_id: str, media_url: str, message: str) -> List[dict]:
        """Process a prescription image via OCR + AI extraction."""
        try:
            raw_text = ocr_service.extract_text_from_url(media_url)
            if not raw_text.strip():
                return [
                    _text(
                        "📸 I received your image but couldn't read any text from it.\n\n"
                        "💡 Tips:\n"
                        "  • Make sure the photo is clear and well-lit\n"
                        "  • Try taking a closer photo\n"
                        "  • Or type the medicine names manually"
                    ),
                    _interactive("menu"),
                ]

            parsed = stepfun_service.extract_medicines_from_ocr_text(raw_text)
            medicines = [m["name"] if isinstance(m, dict) else m for m in parsed]

            if not medicines:
                return [
                    _text(
                        "📸 I scanned your prescription but couldn't identify any medicines.\n\n"
                        "Please try typing the medicine names manually, e.g.:\n"
                        "_\"paracetamol, amoxicillin\"_"
                    ),
                    _interactive("menu"),
                ]

            return await self._search_and_format_medicines(customer_id, medicines, "[prescription scan]")

        except Exception as e:
            logger.error(f"Prescription processing error: {e}")
            return [
                _text("⚠️ Sorry, I had trouble processing that image.\nPlease try again or type the medicine names manually."),
                _interactive("menu"),
            ]

    async def _handle_rating(self, customer_id: str, text: str, history: Optional[List[dict]]) -> List[dict]:
        """Handle 'rate N' or 'rate N comment' messages."""
        parts = text.split(None, 2)
        try:
            score = int(parts[1])
            if score < 1 or score > 5:
                raise ValueError
        except (IndexError, ValueError):
            return [_interactive("rating")]

        comment = parts[2] if len(parts) > 2 else None

        # Find the last pharmacy the customer viewed
        pharmacy_id = await self._get_last_viewed_pharmacy(customer_id, history)
        if not pharmacy_id:
            return [_text(
                "I'm not sure which pharmacy you want to rate.\n"
                "Please view a pharmacy first by searching, then use *rate [1-5]*."
            ), _interactive("menu")]

        await db.create_or_update_rating({
            "customer_id": customer_id,
            "pharmacy_id": pharmacy_id,
            "score": score,
            "comment": comment,
        })

        pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
        name = pharmacy.get("name", "the pharmacy") if pharmacy else "the pharmacy"
        return [
            _text(f"✅ Thanks! You rated *{name}* {_stars(score)} ({score}/5)."),
            _interactive("post_rating"),
        ]

    async def _handle_selection(self, customer_id: str, idx: int, history: Optional[List[dict]]) -> List[dict]:
        """Handle numeric selection from search results."""
        last_results = await self._get_last_search_results(customer_id)
        if not last_results or idx < 1 or idx > len(last_results):
            return [_text(f"Please reply with a number between 1 and {len(last_results) if last_results else '?'}.")]

        pharmacy_id = last_results[idx - 1]
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        if not pharmacy:
            return [_text("Sorry, that pharmacy is no longer available."), _interactive("menu")]

        # Save that the customer is viewing this pharmacy
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"viewing_pharmacy": pharmacy_id}),
        })

        actions = [_text(_fmt_pharmacy_detail(pharmacy))]

        # Send location card if coordinates available
        lat = pharmacy.get("latitude")
        lng = pharmacy.get("longitude")
        if lat and lng:
            name = pharmacy.get("name", "Pharmacy")
            addr = ", ".join(filter(None, [pharmacy.get("address", ""), pharmacy.get("suburb", ""), pharmacy.get("city", "")]))
            actions.append(_location(float(lat), float(lng), name, addr))

        actions.append(_interactive("pharmacy_actions"))
        return actions

    async def _handle_pharmacy_search(self, customer_id: str, query: str) -> List[dict]:
        """Search pharmacies by name or area."""
        if not query:
            return [_text("Please specify a pharmacy name or area, e.g.:\n  *pharmacy Avondale*\n  *pharmacy Greenwood*")]

        results = await db.search_pharmacies_by_name(query)
        if not results:
            results = await db.search_pharmacies_by_area(query)

        if not results:
            return [
                _text(f"😔 No pharmacies found matching *{query}*.\n\n💡 Try a different name or area."),
                _interactive("menu"),
            ]

        lines = [f"🏥 Pharmacies matching *{query}*:\n"]
        pharmacy_ids = []
        for idx, p in enumerate(results[:5], 1):
            pharmacy_ids.append(p["id"])
            lines.append(_fmt_pharmacy_line(idx, p))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")

        # Save result IDs for selection
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"search_results": pharmacy_ids, "type": "pharmacy"}),
        })

        return [_text("\n".join(lines)), _interactive("results_nav")]

    async def _handle_ai_intent(self, customer_id: str, text: str, history: Optional[List[dict]]) -> List[dict]:
        """Use AI to understand intent and route accordingly."""
        try:
            intent = stepfun_service.understand_intent(text, history=history)
        except Exception as e:
            logger.error(f"AI intent error: {e}")
            return [_interactive("menu")]

        intent_type = intent.get("intent", "unknown")
        medicines = intent.get("medicines", [])

        if intent_type == "greeting":
            return [_interactive("welcome")]

        if intent_type == "search_medicine" and medicines:
            return await self._search_and_format_medicines(customer_id, medicines, text)

        if intent_type == "search_pharmacy":
            area = intent.get("area", text)
            return await self._handle_pharmacy_search(customer_id, area)

        if intent_type == "select_result":
            idx = intent.get("selection_index")
            if idx:
                return await self._handle_selection(customer_id, idx, history)

        if intent_type == "request_alternatives" and medicines:
            return await self._search_and_format_medicines(customer_id, medicines, text)

        # Default: try medicine search if we found any medicine names
        if medicines:
            return await self._search_and_format_medicines(customer_id, medicines, text)

        return [_text("🤔 I'm not sure what you're looking for."), _interactive("menu")]

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _search_and_format_medicines(
        self, customer_id: str, medicines: List[str], query: str
    ) -> List[dict]:
        """Search medicines, log analytics, format results."""
        results = await search_service.find_medicines(medicines)
        await analytics_service.log_search(customer_id, query, results)

        if not results:
            names = ", ".join(medicines)
            return [
                _text(
                    f"😔 Sorry, I couldn't find *{names}* in stock at any pharmacy.\n\n"
                    "💡 Try:\n"
                    "  • A different spelling or generic name\n"
                    "  • Describing your symptoms instead"
                ),
                _interactive("menu"),
            ]

        # Collect pharmacy IDs for selection
        all_pharmacy_ids = []
        response_parts = []

        for med in results:
            pharmacies = med.get("pharmacies", [])
            med_name = med.get("name", "Unknown")

            for inv in pharmacies[:5]:
                p = inv.get("pharmacies") or {}
                p_id = p.get("id") or inv.get("pharmacy_id")
                if p_id and p_id not in all_pharmacy_ids:
                    all_pharmacy_ids.append(p_id)

            response_parts.append(_fmt_medicine_results(med_name, pharmacies))

        # Save result IDs for numeric selection
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"search_results": all_pharmacy_ids, "type": "medicine"}),
        })

        return [_text("\n\n".join(response_parts)), _interactive("results_nav")]

    async def _get_last_search_results(self, customer_id: str) -> Optional[List[str]]:
        """Get pharmacy IDs from the last search results in conversation."""
        history = await db.get_conversation_history(customer_id, limit=20)
        for msg in reversed(history):
            if msg.get("role") == "system":
                try:
                    data = json.loads(msg.get("content", "{}"))
                    if "search_results" in data:
                        return data["search_results"]
                except (json.JSONDecodeError, TypeError):
                    continue
        return None

    async def _get_last_viewed_pharmacy(self, customer_id: str, history: Optional[List[dict]]) -> Optional[str]:
        """Get the last pharmacy ID the customer viewed."""
        rows = await db.get_conversation_history(customer_id, limit=20)
        for msg in reversed(rows):
            if msg.get("role") == "system":
                try:
                    data = json.loads(msg.get("content", "{}"))
                    if "viewing_pharmacy" in data:
                        return data["viewing_pharmacy"]
                except (json.JSONDecodeError, TypeError):
                    continue
        return None


whatsapp_service = WhatsAppService()
