"""
WhatsApp conversation orchestrator.

State machine flow:
  STATE 1 — MAIN MENU (welcome, numbered options)
  STATE 2 — MEDICINE SEARCH (plain name, symptom via LLM, image via OCR, bulk list)
  STATE 3 — RESULTS LIST (ranked pharmacies with stock info)
  STATE 4 — PHARMACY DETAIL (location pin + info card + CTA buttons)
  STATE 5 — RATING (1-5, optional comment)

Global rules:
  - 0 / menu / home / back → main menu from any state
  - help / ? → help message
  - GPS location pin → save coords
  - Max 2 messages per bot turn
  - Every message ends with an italic next-step hint

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

RATING_LABELS = {1: "Poor", 2: "Below average", 3: "Average", 4: "Good", 5: "Excellent"}

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

def _cta(body: str, actions: list) -> dict:
    """Call-to-action message action (phone/URL buttons)."""
    return {"type": "cta", "body": body, "actions": actions}

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
    """Format a full pharmacy detail card — matches system prompt spec."""
    hours_data = _parse_opening_hours(p.get("opening_hours"))
    status = _open_status_badge(hours_data)

    lines = [f"🏥 *{p.get('name', 'Unknown')}*"]
    if status:
        lines.append(status)
    lines.append("")

    # Address + Maps link
    loc = ", ".join(filter(None, [p.get("address", ""), p.get("suburb", ""), p.get("city", "")]))
    if loc:
        lines.append("*📍 Address*")
        lat, lng = p.get("latitude"), p.get("longitude")
        if lat and lng:
            lines.append(f"{loc}")
            lines.append(f"🗺️ https://maps.google.com/?q={lat},{lng}")
        else:
            lines.append(loc)
        lines.append("")

    # Phone
    phone = p.get("phone")
    if phone:
        lines.append(f"� {phone}")
        lines.append("")

    # Opening Hours
    if hours_data:
        lines.append("*🕐 Hours*")
        lines.append(_fmt_opening_hours_detail(hours_data))
        lines.append("")

    # Services — only show TRUE flags
    services = []
    if p.get("accepts_medical_aid"):
        services.append("🏥 Accepts Medical Aid")
    if p.get("parking_available"):
        services.append("� Parking Available")
    if p.get("has_delivery"):
        services.append("� Delivery Available")
    if p.get("is_24_hours"):
        services.append("� Open 24 Hours")
    special = p.get("special_services")
    if special:
        services.append(f"ℹ️ {special}")
    if services:
        lines.append("*ℹ️ Services*")
        for s in services:
            lines.append(s)
        lines.append("")

    # Links — only show non-null
    links = []
    website = p.get("website")
    if website:
        links.append(f"🌐 {website}")
    fb = p.get("facebook")
    if fb:
        links.append(f"📘 {fb}")
    ig = p.get("instagram")
    if ig:
        links.append(f"📸 {ig}")
    wa = p.get("whatsapp_number")
    if wa:
        wa_clean = wa.strip().replace(" ", "").replace("+", "")
        links.append(f"💬 wa.me/{wa_clean}")
    if links:
        lines.append("*🌐 Links*")
        for lnk in links:
            lines.append(lnk)
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("Reply *rate* to rate · *save* to save · *back* for list")
    lines.append("_Reply *0* for main menu_")
    return "\n".join(lines)


def _fmt_medicine_results(medicine_name: str, pharmacies: list) -> str:
    """Format medicine search results — ranked, grouped by open/closed."""
    if not pharmacies:
        return (
            f"😔 *{medicine_name}*\n"
            "No results found.\n\n"
            "Try a different spelling, the generic name, or describe your symptoms.\n\n"
            "_Reply *0* for main menu_"
        )

    ranked = _rank_pharmacy_results(pharmacies)
    count = len(ranked)

    # Group by open/closed
    open_items = []
    closed_items = []
    for inv in ranked[:5]:
        p = inv.get("pharmacies") or inv
        hours_data = _parse_opening_hours(p.get("opening_hours"))
        is_open = _is_pharmacy_open(hours_data)
        if is_open is False:
            closed_items.append(inv)
        else:
            open_items.append(inv)

    lines = [f"💊 *{count} pharmacy{'ies' if count != 1 else ''}* with *{medicine_name}*\n"]

    idx = 1
    if open_items:
        lines.append("🟢 *Open Now*")
        for inv in open_items:
            p = inv.get("pharmacies") or inv
            lines.append(_fmt_pharmacy_line(idx, p, inv=inv))
            lines.append("")
            idx += 1

    if closed_items:
        lines.append("🔴 *Closed*")
        for inv in closed_items:
            p = inv.get("pharmacies") or inv
            lines.append(_fmt_pharmacy_line(idx, p, inv=inv))
            lines.append("")
            idx += 1

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Reply with a number for full details_")
    lines.append("_Type a new medicine name to search again_")
    lines.append("_Reply *0* for main menu_")
    return "\n".join(lines)


class WhatsAppService:
    """Orchestrates the WhatsApp conversation flow — state machine."""

    # ── Welcome message text ────────────────────────────────────────────
    WELCOME = (
        "👋 *Welcome to RERUN Health!*\n"
        "I help you find medicines at pharmacies near you.\n\n"
        "*What would you like to do?*\n\n"
        "1️⃣ 💊 Find a medicine\n"
        "2️⃣ 📍 Pharmacies near me\n"
        "3️⃣ 💾 My saved pharmacies\n\n"
        "_Or just tell me what you're looking for!_\n"
        "_Reply *0* anytime for this menu_"
    )

    HELP = (
        "ℹ️ *RERUN Health — Help*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💊 *Find Medicine* — Type any medicine name\n"
        "📍 *Near Me* — Find pharmacies in your area\n"
        "💾 *Saved* — View your saved pharmacies\n"
        "📸 *Photo* — Send a prescription photo\n"
        "⭐ *Rate* — Rate a pharmacy after viewing\n"
        "💾 *Save* — Save a pharmacy you're viewing\n\n"
        "_Just type what you need!_\n"
        "_Reply *0* for main menu_"
    )

    SEARCH_PROMPT = (
        "💊 *What medicine are you looking for?*\n\n"
        "Type a medicine name, describe symptoms, or send a photo.\n\n"
        "_e.g. paracetamol, \"I have a headache\", amoxicillin 500mg_\n"
        "_Reply *0* for main menu_"
    )

    LOCATION_PROMPT = (
        "📍 *Find pharmacies near you*\n\n"
        "Send your location pin 📌 or type an area name.\n\n"
        "_e.g. Avondale, Borrowdale, City Centre_\n"
        "_Reply *0* for main menu_"
    )

    async def process_message(
        self,
        customer_id: str,
        message: str,
        media_url: Optional[str] = None,
        history: Optional[List[dict]] = None,
    ) -> List[dict]:
        """Main entry point. Returns a list of message actions to send (max 2)."""

        # ── Prescription / medicine image ──
        if media_url:
            return await self._handle_prescription(customer_id, media_url, message)

        text = message.strip()
        lower = text.lower()

        # ── GLOBAL RULES — always active ──
        if lower in ("0", "menu", "home", "back", "main menu", "🏠 main menu", "📋 menu"):
            return [_text(self.WELCOME)]
        if lower in ("help", "?", "❓ help"):
            return [_text(self.HELP)]

        # ── STATE 1 — Main menu triggers ──
        if lower in ("hi", "hello", "hey", "start", "hie"):
            return [_text(self.WELCOME)]
        if lower in ("1", "find", "find medicine", "💊", "find a medicine", "💊 find medicine"):
            return [_text(self.SEARCH_PROMPT)]
        if lower in ("2", "near me", "nearby", "�", "📍 near me", "pharmacies near me"):
            return [_text(self.LOCATION_PROMPT)]
        if lower in ("3", "saved", "💾", "my saved", "💾 my saved pharmacies"):
            return await self._handle_saved_pharmacies(customer_id)

        # ── Quick reply button responses ──
        if lower in ("scan rx", "📸 scan rx"):
            return [_text("📸 Send a photo of your prescription and I'll identify the medicines for you.\n\n_Reply *0* for main menu_")]
        if lower in ("rate", "⭐ rate"):
            return await self._show_rating_prompt(customer_id)
        if lower in ("save", "💾 save"):
            return await self._handle_save_pharmacy(customer_id)

        # ── Rating quick reply responses ──
        if lower in ("⭐⭐⭐⭐⭐ (5)", "rate_5"):
            return await self._handle_rating(customer_id, 5, history)
        if lower in ("⭐⭐⭐⭐ (4)", "rate_4"):
            return await self._handle_rating(customer_id, 4, history)
        if lower in ("⭐⭐⭐ (3)", "rate_3"):
            return await self._handle_rating(customer_id, 3, history)

        # ── Rating (typed) — "rate 4" or "rate 5 great service" ──
        if lower.startswith("rate "):
            parts = text.split(None, 2)
            try:
                score = int(parts[1])
                if 1 <= score <= 5:
                    comment = parts[2] if len(parts) > 2 else None
                    return await self._handle_rating(customer_id, score, history, comment=comment)
            except (IndexError, ValueError):
                pass
            return await self._show_rating_prompt(customer_id)

        # ── Skip (rating comment skip) ──
        if lower == "skip":
            state = await self._get_session_state(customer_id)
            if state and state.get("awaiting_comment"):
                return await self._finalize_rating(customer_id, state["awaiting_comment"]["score"], None, state["awaiting_comment"]["pharmacy_id"])
            return [_text(self.WELCOME)]

        # ── Numeric selection (picking from results) ──
        if lower.isdigit() and int(lower) > 0:
            return await self._handle_selection(customer_id, int(lower), history)

        # ── Pharmacy search ──
        if lower.startswith("pharmacy ") or lower.startswith("find pharmacy"):
            query = text.split(" ", 1)[1] if " " in text else ""
            return await self._handle_pharmacy_search(customer_id, query.strip())

        # ── New search (quick reply button) ──
        if lower in ("new search", "🔍 new search"):
            return [_text(self.SEARCH_PROMPT)]

        # ── Check if user is submitting a rating comment ──
        state = await self._get_session_state(customer_id)
        if state and state.get("awaiting_comment"):
            ac = state["awaiting_comment"]
            return await self._finalize_rating(customer_id, ac["score"], text, ac["pharmacy_id"])

        # ── Fallback: treat as medicine search or use AI ──
        return await self._handle_ai_intent(customer_id, text, history)

    # ── Handlers ────────────────────────────────────────────────────────────

    async def _handle_prescription(self, customer_id: str, media_url: str, message: str) -> List[dict]:
        """Process a prescription image via OCR + AI extraction."""
        try:
            raw_text = ocr_service.extract_text_from_url(media_url)
            logger.info(f"[OCR] user_id={customer_id} extracted=\"{raw_text[:200]}\"")
            if not raw_text.strip():
                return [_text(
                    "� I couldn't read the image clearly. Please type the medicine name instead.\n\n"
                    "_Reply *0* for main menu_"
                )]

            parsed = stepfun_service.extract_medicines_from_ocr_text(raw_text)
            medicines = [m["name"] if isinstance(m, dict) else m for m in parsed]

            if not medicines:
                return [_text(
                    "� I couldn't read the image clearly. Please type the medicine name instead.\n\n"
                    "_Reply *0* for main menu_"
                )]

            names_str = ", ".join(f"*{m}*" for m in medicines)
            return [
                _text(f"📸 I scanned your image and found: {names_str}. Searching..."),
            ] + await self._search_and_format_medicines(customer_id, medicines, "[prescription scan]")

        except Exception as e:
            logger.error(f"Prescription processing error: {e}")
            return [_text(
                "😔 I couldn't read the image clearly. Please type the medicine name instead.\n\n"
                "_Reply *0* for main menu_"
            )]

    async def _show_rating_prompt(self, customer_id: str) -> List[dict]:
        """Show the rating selection prompt."""
        pharmacy_id = await self._get_last_viewed_pharmacy(customer_id)
        if not pharmacy_id:
            return [_text(
                "Please view a pharmacy first, then reply *rate*.\n\n"
                "_Reply *0* for main menu_"
            )]
        pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
        name = pharmacy.get("name", "this pharmacy") if pharmacy else "this pharmacy"
        return [_text(
            f"⭐ *Rate {name}*\n\n"
            "1️⃣ Poor\n"
            "2️⃣ Below average\n"
            "3️⃣ Average\n"
            "4️⃣ Good\n"
            "5️⃣ Excellent\n\n"
            "_Reply *0* for main menu_"
        )]

    async def _handle_rating(self, customer_id: str, score: int, history: Optional[List[dict]], comment: str = None) -> List[dict]:
        """Handle rating with optional inline comment, or prompt for comment."""
        pharmacy_id = await self._get_last_viewed_pharmacy(customer_id)
        if not pharmacy_id:
            return [_text(
                "Please view a pharmacy first, then reply *rate*.\n\n"
                "_Reply *0* for main menu_"
            )]

        if comment:
            return await self._finalize_rating(customer_id, score, comment, pharmacy_id)

        # Save state: awaiting comment
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"awaiting_comment": {"score": score, "pharmacy_id": pharmacy_id}}),
        })

        return [_text(
            f"{_stars(score)} Thanks!\n\n"
            "Leave a comment? Type it now or reply *skip*"
        )]

    async def _finalize_rating(self, customer_id: str, score: int, comment: Optional[str], pharmacy_id: str) -> List[dict]:
        """Save rating and return confirmation."""
        await db.create_or_update_rating({
            "customer_id": customer_id,
            "pharmacy_id": pharmacy_id,
            "score": score,
            "comment": comment,
        })
        return [_text(
            "✅ Rating saved! Thank you for helping others. 🙏\n\n"
            "_Reply *0* for main menu_"
        )]

    async def _handle_save_pharmacy(self, customer_id: str) -> List[dict]:
        """Save the currently viewed pharmacy."""
        pharmacy_id = await self._get_last_viewed_pharmacy(customer_id)
        if not pharmacy_id:
            return [_text(
                "Please view a pharmacy first, then reply *save*.\n\n"
                "_Reply *0* for main menu_"
            )]
        try:
            await db.save_pharmacy_for_customer(customer_id, pharmacy_id)
            pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
            name = pharmacy.get("name", "Pharmacy") if pharmacy else "Pharmacy"
            return [_text(
                f"💾 *{name}* saved!\n\n"
                "Reply *saved* to view all your saved pharmacies.\n"
                "_Reply *0* for main menu_"
            )]
        except Exception as e:
            logger.error(f"Save pharmacy error: {e}")
            return [_text("⚠️ Couldn't save that pharmacy. Please try again.\n\n_Reply *0* for main menu_")]

    async def _handle_saved_pharmacies(self, customer_id: str) -> List[dict]:
        """Show the customer's saved pharmacies."""
        try:
            saved = await db.get_saved_pharmacies(customer_id)
        except Exception as e:
            logger.error(f"Saved pharmacies error: {e}")
            saved = []

        if not saved:
            return [_text(
                "💾 *My Saved Pharmacies*\n\n"
                "You haven't saved any pharmacies yet. Search for one to get started.\n\n"
                "_Reply *1* to find a medicine or *0* for main menu_"
            )]

        lines = ["💾 *My Saved Pharmacies*\n"]
        pharmacy_ids = []
        for idx, row in enumerate(saved[:10], 1):
            p = row.get("pharmacies") or {}
            if not p.get("id"):
                continue
            pharmacy_ids.append(p["id"])
            lines.append(_fmt_pharmacy_line(idx, p))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Reply with a number for full details_")
        lines.append("_Reply *0* for main menu_")

        # Save IDs for numeric selection
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"search_results": pharmacy_ids, "type": "saved"}),
        })

        return [_text("\n".join(lines))]

    async def _handle_selection(self, customer_id: str, idx: int, history: Optional[List[dict]]) -> List[dict]:
        """Handle numeric selection from results list → STATE 4 pharmacy detail."""
        last_results = await self._get_last_search_results(customer_id)
        if not last_results or idx < 1 or idx > len(last_results):
            return [_text(f"Please reply with a number between 1 and {len(last_results) if last_results else '?'}.\n\n_Reply *0* for main menu_")]

        pharmacy_id = last_results[idx - 1]
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        if not pharmacy:
            return [_text("Sorry, that pharmacy is no longer available.\n\n_Reply *0* for main menu_")]

        # Save that the customer is viewing this pharmacy
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"viewing_pharmacy": pharmacy_id}),
        })

        actions = []

        # Message 1: Location pin (if coords available)
        lat = pharmacy.get("latitude")
        lng = pharmacy.get("longitude")
        name = pharmacy.get("name", "Pharmacy")
        if lat and lng:
            addr = ", ".join(filter(None, [pharmacy.get("address", ""), pharmacy.get("suburb", ""), pharmacy.get("city", "")]))
            actions.append(_location(float(lat), float(lng), name, addr))

        # Message 2: Info card
        actions.append(_text(_fmt_pharmacy_detail(pharmacy)))

        return actions

    async def _handle_pharmacy_search(self, customer_id: str, query: str) -> List[dict]:
        """Search pharmacies by name or area."""
        if not query:
            return [_text(self.LOCATION_PROMPT)]

        results = await db.search_pharmacies_by_name(query)
        if not results:
            results = await db.search_pharmacies_by_area(query)

        if not results:
            return [_text(
                f"😔 No pharmacies found matching *{query}*.\n"
                "• Try a shorter name or generic alternative\n"
                "• Share your 📍 location for a wider search\n"
                "• Type a different area name\n\n"
                "_Reply *0* for main menu_"
            )]

        lines = [f"🏥 Pharmacies matching *{query}*:\n"]
        pharmacy_ids = []
        for idx, p in enumerate(results[:5], 1):
            pharmacy_ids.append(p["id"])
            lines.append(_fmt_pharmacy_line(idx, p))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Reply with a number for full details_")
        lines.append("_Type a new medicine name to search again_")
        lines.append("_Reply *0* for main menu_")

        # Save result IDs for selection
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"search_results": pharmacy_ids, "type": "pharmacy"}),
        })

        return [_text("\n".join(lines))]

    async def _handle_ai_intent(self, customer_id: str, text: str, history: Optional[List[dict]]) -> List[dict]:
        """Use AI to understand intent and route accordingly."""
        try:
            intent = stepfun_service.understand_intent(text, history=history)
        except Exception as e:
            logger.error(f"AI intent error: {e}")
            # Fallback: treat raw input as medicine search
            return await self._search_and_format_medicines(customer_id, [text], text)

        intent_type = intent.get("intent", "unknown")
        medicines = intent.get("medicines", [])

        logger.info(f"[INTENT] user_id={customer_id} raw=\"{text}\" intent={intent_type} medicines={medicines}")

        if intent_type == "greeting":
            return [_text(self.WELCOME)]

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

        # Default: try medicine search with whatever we have
        if medicines:
            return await self._search_and_format_medicines(customer_id, medicines, text)

        # Last resort: treat raw text as medicine search
        return await self._search_and_format_medicines(customer_id, [text], text)

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _search_and_format_medicines(
        self, customer_id: str, medicines: List[str], query: str
    ) -> List[dict]:
        """Search medicines, log analytics, format results. Auto-add unverified if not found."""
        results = await search_service.find_medicines(medicines)
        await analytics_service.log_search(customer_id, query, results)

        if not results:
            # Add unverified medicines for admin review
            for med_name in medicines:
                await db.add_unverified_medicine(med_name.strip(), added_by=customer_id)

            names = ", ".join(f"*{m}*" for m in medicines)
            return [_text(
                f"� No pharmacies found with {names} nearby.\n"
                "• Try a shorter name or generic alternative\n"
                "• Share your 📍 location for a wider search\n"
                "• Type a different medicine name\n\n"
                "_Reply *0* for main menu_"
            )]

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

        return [_text("\n\n".join(response_parts))]

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

    async def _get_last_viewed_pharmacy(self, customer_id: str, history: Optional[List[dict]] = None) -> Optional[str]:
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

    async def _get_session_state(self, customer_id: str) -> Optional[dict]:
        """Get the latest session state from conversation (e.g. awaiting_comment)."""
        rows = await db.get_conversation_history(customer_id, limit=5)
        for msg in reversed(rows):
            if msg.get("role") == "system":
                try:
                    data = json.loads(msg.get("content", "{}"))
                    if "awaiting_comment" in data:
                        return data
                except (json.JSONDecodeError, TypeError):
                    continue
        return None


whatsapp_service = WhatsAppService()
