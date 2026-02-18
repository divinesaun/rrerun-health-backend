"""
WhatsApp conversation orchestrator.

Manages the full customer conversation flow:
  - Medicine search
  - Pharmacy search (by name / area)
  - Pharmacy details
  - Rating pharmacies
  - Prescription image handling
  - Menu / help
"""

import json
from typing import Dict, List, Optional

from loguru import logger

from app import database as db
from app.services.stepfun_service import stepfun_service
from app.services.search_service import search_service
from app.services.analytics_service import analytics_service
from app.services.ocr_service import ocr_service


# ── Formatting helpers ──────────────────────────────────────────────────────

def _stars(score: float) -> str:
    full = int(score)
    return "⭐" * full + ("½" if score - full >= 0.5 else "")


def _fmt_pharmacy_line(idx: int, p: dict, price: str = None) -> str:
    """Format a single pharmacy result line for WhatsApp."""
    parts = [f"*{idx}. {p.get('name', 'Unknown')}*"]
    if price is not None:
        parts.append(f"   💰 ${price}")
    rating = p.get("rating")
    if rating:
        parts.append(f"   {_stars(float(rating))} ({p.get('total_reviews', 0)} reviews)")
    addr = p.get("address", "")
    suburb = p.get("suburb", "")
    if suburb:
        addr = f"{addr}, {suburb}"
    if addr:
        parts.append(f"   📍 {addr}")
    dist = p.get("distance_km")
    if dist is not None:
        parts.append(f"   📏 {dist} km away")
    phone = p.get("whatsapp_number") or p.get("phone")
    if phone:
        parts.append(f"   📞 {phone}")
    services = []
    if p.get("has_delivery"):
        services.append("🚚 Delivery")
    if p.get("accepts_medical_aid"):
        services.append("💳 Medical Aid")
    if p.get("is_24_hours"):
        services.append("🕐 24hrs")
    if services:
        parts.append(f"   {' · '.join(services)}")
    return "\n".join(parts)


def _fmt_pharmacy_detail(p: dict) -> str:
    """Format a full pharmacy detail card."""
    lines = [
        f"🏥 *{p.get('name', 'Unknown')}*",
        "",
    ]
    rating = p.get("rating")
    if rating:
        lines.append(f"⭐ Rating: {rating}/5 ({p.get('total_reviews', 0)} reviews)")
    addr = p.get("address", "")
    suburb = p.get("suburb", "")
    city = p.get("city", "")
    loc = ", ".join(filter(None, [addr, suburb, city]))
    if loc:
        lines.append(f"📍 {loc}")
    phone = p.get("phone")
    if phone:
        lines.append(f"📞 Phone: {phone}")
    wa = p.get("whatsapp_number")
    if wa:
        lines.append(f"💬 WhatsApp: {wa}")
    hours = p.get("opening_hours")
    if hours:
        lines.append(f"🕐 Hours: {hours}")

    lines.append("")
    lines.append("*Services:*")
    if p.get("accepts_medical_aid"):
        lines.append("  ✅ Accepts Medical Aid")
    if p.get("has_delivery"):
        lines.append("  ✅ Delivery Service")
    if p.get("is_24_hours"):
        lines.append("  ✅ Open 24 Hours")
    if p.get("parking_available"):
        lines.append("  ✅ Parking Available")
    special = p.get("special_services")
    if special:
        lines.append(f"  ℹ️ {special}")

    website = p.get("website")
    if website:
        lines.append(f"\n🌐 {website}")

    lines.append("")
    lines.append("_Reply *rate [1-5]* to rate this pharmacy_")
    lines.append("_Reply *menu* to go back_")
    return "\n".join(lines)


def _fmt_medicine_results(medicine_name: str, pharmacies: list) -> str:
    """Format medicine search results."""
    if not pharmacies:
        return (
            f"😔 Sorry, *{medicine_name}* is not currently in stock at any pharmacy.\n\n"
            "💡 Try:\n"
            "  • A different spelling\n"
            "  • The generic name\n"
            "  • Describing your symptoms\n\n"
            "_Reply *menu* for options_"
        )

    lines = [
        f"💊 *{medicine_name}* — found at {len(pharmacies)} pharmacy{'s' if len(pharmacies) != 1 else ''}:\n"
    ]
    for idx, inv in enumerate(pharmacies[:5], 1):
        p = inv.get("pharmacies") or inv
        price = inv.get("price", "—")
        qty = inv.get("quantity_available", "")
        stock_note = f" ({qty} available)" if qty else ""
        line = _fmt_pharmacy_line(idx, p, price=f"{price}{stock_note}")
        lines.append(line)
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📌 Reply with a *number* (1-5) to see full pharmacy details")
    lines.append("💊 Or send another medicine name to search")
    lines.append("📋 Reply *menu* to see all options")
    return "\n".join(lines)


MENU_TEXT = (
    "🏥 *RERUN Health* — Your Pharmacy Assistant\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Here's what I can do:\n\n"
    "💊 *Search medicine* — just type a medicine name\n"
    "   _e.g. \"paracetamol\" or \"headache medicine\"_\n\n"
    "🏥 *Find pharmacy* — type \"pharmacy [name or area]\"\n"
    "   _e.g. \"pharmacy Avondale\" or \"pharmacy Greenwood\"_\n\n"
    "📸 *Prescription scan* — send a photo of your prescription\n\n"
    "⭐ *Rate a pharmacy* — type \"rate [1-5]\" after viewing details\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "Just type what you need and I'll help! 😊"
)

GREETING_TEXT = (
    "👋 *Welcome to RERUN Health!*\n\n"
    "I help you find medicines at pharmacies near you in Zimbabwe — "
    "with prices, stock info, and ratings.\n\n"
    + MENU_TEXT.split("Here's what I can do:\n\n", 1)[1]
)


class WhatsAppService:
    """Orchestrates the WhatsApp conversation flow."""

    async def process_message(
        self,
        customer_id: str,
        message: str,
        media_url: Optional[str] = None,
        history: Optional[List[dict]] = None,
    ) -> str:
        """Main entry point. Returns the bot response text."""

        # ── Prescription image ──
        if media_url:
            return await self._handle_prescription(customer_id, media_url, message)

        text = message.strip()
        lower = text.lower()

        # ── Direct commands ──
        if lower in ("menu", "help", "hi", "hello", "hey", "start"):
            if lower in ("hi", "hello", "hey", "start"):
                return GREETING_TEXT
            return MENU_TEXT

        # ── Rating (after viewing pharmacy details) ──
        if lower.startswith("rate "):
            return await self._handle_rating(customer_id, text, history)

        # ── Numeric selection (picking from results) ──
        if lower.isdigit():
            return await self._handle_selection(customer_id, int(lower), history)

        # ── Pharmacy search ──
        if lower.startswith("pharmacy ") or lower.startswith("find pharmacy"):
            query = text.split(" ", 1)[1] if " " in text else ""
            return await self._handle_pharmacy_search(customer_id, query.strip())

        # ── Fallback: use AI to understand intent ──
        return await self._handle_ai_intent(customer_id, text, history)

    # ── Handlers ────────────────────────────────────────────────────────────

    async def _handle_prescription(self, customer_id: str, media_url: str, message: str) -> str:
        """Process a prescription image via OCR + AI extraction."""
        try:
            raw_text = ocr_service.extract_text_from_url(media_url)
            if not raw_text.strip():
                return (
                    "📸 I received your image but couldn't read any text from it.\n\n"
                    "💡 Tips:\n"
                    "  • Make sure the photo is clear and well-lit\n"
                    "  • Try taking a closer photo\n"
                    "  • Or type the medicine names manually"
                )

            parsed = stepfun_service.extract_medicines_from_ocr_text(raw_text)
            medicines = [m["name"] if isinstance(m, dict) else m for m in parsed]

            if not medicines:
                return (
                    "📸 I scanned your prescription but couldn't identify any medicines.\n\n"
                    "Please try typing the medicine names manually, e.g.:\n"
                    "_\"paracetamol, amoxicillin\"_"
                )

            return await self._search_and_format_medicines(customer_id, medicines, "[prescription scan]")

        except Exception as e:
            logger.error(f"Prescription processing error: {e}")
            return (
                "⚠️ Sorry, I had trouble processing that image.\n"
                "Please try again or type the medicine names manually."
            )

    async def _handle_rating(self, customer_id: str, text: str, history: Optional[List[dict]]) -> str:
        """Handle 'rate N' or 'rate N comment' messages."""
        parts = text.split(None, 2)
        try:
            score = int(parts[1])
            if score < 1 or score > 5:
                raise ValueError
        except (IndexError, ValueError):
            return "Please rate from 1 to 5, e.g. *rate 4* or *rate 5 Great service!*"

        comment = parts[2] if len(parts) > 2 else None

        # Find the last pharmacy the customer viewed
        pharmacy_id = await self._get_last_viewed_pharmacy(customer_id, history)
        if not pharmacy_id:
            return (
                "I'm not sure which pharmacy you want to rate.\n"
                "Please view a pharmacy first by searching, then use *rate [1-5]*."
            )

        await db.create_or_update_rating({
            "customer_id": customer_id,
            "pharmacy_id": pharmacy_id,
            "score": score,
            "comment": comment,
        })

        pharmacy = await db.get_pharmacy_by_id(pharmacy_id)
        name = pharmacy.get("name", "the pharmacy") if pharmacy else "the pharmacy"
        return f"✅ Thanks! You rated *{name}* {_stars(score)} ({score}/5).\n\n_Reply *menu* for options_"

    async def _handle_selection(self, customer_id: str, idx: int, history: Optional[List[dict]]) -> str:
        """Handle numeric selection from search results."""
        # Look through recent bot messages for pharmacy IDs embedded in metadata
        last_results = await self._get_last_search_results(customer_id)
        if not last_results or idx < 1 or idx > len(last_results):
            return f"Please reply with a number between 1 and {len(last_results) if last_results else '?'}."

        pharmacy_id = last_results[idx - 1]
        pharmacy = await db.get_pharmacy_details(pharmacy_id)
        if not pharmacy:
            return "Sorry, that pharmacy is no longer available."

        # Save that the customer is viewing this pharmacy
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"viewing_pharmacy": pharmacy_id}),
        })

        return _fmt_pharmacy_detail(pharmacy)

    async def _handle_pharmacy_search(self, customer_id: str, query: str) -> str:
        """Search pharmacies by name or area."""
        if not query:
            return "Please specify a pharmacy name or area, e.g.:\n  *pharmacy Avondale*\n  *pharmacy Greenwood*"

        # Try name search first, then area
        results = await db.search_pharmacies_by_name(query)
        if not results:
            results = await db.search_pharmacies_by_area(query)

        if not results:
            return (
                f"😔 No pharmacies found matching *{query}*.\n\n"
                "💡 Try a different name or area.\n"
                "_Reply *menu* for options_"
            )

        lines = [f"🏥 Pharmacies matching *{query}*:\n"]
        pharmacy_ids = []
        for idx, p in enumerate(results[:5], 1):
            pharmacy_ids.append(p["id"])
            lines.append(_fmt_pharmacy_line(idx, p))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📌 Reply with a *number* to see full details")
        lines.append("📋 Reply *menu* to see all options")

        # Save result IDs for selection
        await db.save_conversation_message({
            "customer_id": customer_id,
            "role": "system",
            "content": json.dumps({"search_results": pharmacy_ids, "type": "pharmacy"}),
        })

        return "\n".join(lines)

    async def _handle_ai_intent(self, customer_id: str, text: str, history: Optional[List[dict]]) -> str:
        """Use AI to understand intent and route accordingly."""
        try:
            intent = stepfun_service.understand_intent(text, history=history)
        except Exception as e:
            logger.error(f"AI intent error: {e}")
            return MENU_TEXT

        intent_type = intent.get("intent", "unknown")
        medicines = intent.get("medicines", [])

        if intent_type == "greeting":
            return GREETING_TEXT

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

        return (
            "🤔 I'm not sure what you're looking for.\n\n"
            + MENU_TEXT
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _search_and_format_medicines(
        self, customer_id: str, medicines: List[str], query: str
    ) -> str:
        """Search medicines, log analytics, format results."""
        results = await search_service.find_medicines(medicines)
        await analytics_service.log_search(customer_id, query, results)

        if not results:
            names = ", ".join(medicines)
            return (
                f"😔 Sorry, I couldn't find *{names}* in stock at any pharmacy.\n\n"
                "💡 Try:\n"
                "  • A different spelling or generic name\n"
                "  • Describing your symptoms instead\n\n"
                "_Reply *menu* for options_"
            )

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

        return "\n\n".join(response_parts)

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
