"""
Live end-to-end simulation of WhatsApp conversation flows.

Calls process_message directly (no HTTP) with a real customer ID against
the live Supabase database. Prints every response so you can see exactly
what the bot says at each step.

Usage:
    python -m tests.live_simulation
"""

import asyncio
import json
import sys

from loguru import logger

# Configure loguru to show ROUTE and LLM logs clearly
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")

from app.services.whatsapp_service import whatsapp_service, _read_session, _save_session
from app.services.auth_service import auth_service
from app import database as db

PHONE = "whatsapp:+263770000099"  # test number
DIVIDER = "=" * 60


async def send(msg: str, media_url=None):
    """Simulate sending a message and print the bot's response."""
    print(f"\n{DIVIDER}")
    print(f"👤 USER: {msg or '[image]'}")
    if media_url:
        print(f"   📎 media: {media_url}")
    print(DIVIDER)

    customer = await auth_service.get_or_create_customer(PHONE)
    cid = customer["id"]

    history_rows = await db.get_conversation_history(cid, limit=10)
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in history_rows
        if r.get("role") in ("user", "assistant")
    ]

    # Save user message
    await db.save_conversation_message({
        "customer_id": cid,
        "role": "user",
        "content": msg or "[image]",
    })

    actions = await whatsapp_service.process_message(
        customer_id=cid,
        message=msg,
        media_url=media_url,
        history=history,
    )

    # Save assistant response
    text_parts = [a["body"] for a in actions if a.get("type") == "text"]
    if text_parts:
        await db.save_conversation_message({
            "customer_id": cid,
            "role": "assistant",
            "content": "\n\n".join(text_parts),
        })

    for i, action in enumerate(actions):
        atype = action.get("type", "?")
        if atype == "text":
            print(f"\n🤖 BOT (text):")
            print(action["body"])
        elif atype == "location":
            print(f"\n🤖 BOT (location pin):")
            print(f"   📍 {action.get('label')} — {action.get('address', '')}")
            print(f"   lat={action.get('lat')}, lng={action.get('lng')}")
        else:
            print(f"\n🤖 BOT ({atype}): {json.dumps(action, default=str)[:200]}")

    # Show session state
    session = await _read_session(cid)
    print(f"\n📦 SESSION: {json.dumps(session, default=str)[:200]}")
    return actions


async def run_all_flows():
    print("\n" + "🔬 " * 20)
    print("WHATSAPP BOT — LIVE CONVERSATION SIMULATION")
    print("🔬 " * 20)

    # ── Flow 1: Greeting ──
    print("\n\n### FLOW 1: GREETING ###")
    await send("hi")

    # ── Flow 2: Menu commands ──
    print("\n\n### FLOW 2: MENU COMMANDS ###")
    await send("0")
    await send("menu")
    await send("help")

    # ── Flow 3: Search medicine → select → view detail ──
    print("\n\n### FLOW 3: MEDICINE SEARCH → SELECT ###")
    results = await send("paracetamol")
    # Try selecting #1
    await send("1")

    # ── Flow 4: Number without results → menu items ──
    print("\n\n### FLOW 4: NUMBER → MENU (no results context) ###")
    await send("0")  # reset
    await send("1")  # should show search prompt
    await send("0")  # reset
    await send("2")  # should show near me
    await send("0")  # reset
    await send("3")  # should show saved

    # ── Flow 5: Symptom detection ──
    print("\n\n### FLOW 5: SYMPTOM DETECTION ###")
    await send("I have a headache")

    # ── Flow 6: Pharmacy search ──
    print("\n\n### FLOW 6: PHARMACY SEARCH ###")
    await send("pharmacy Avondale")
    await send("pharmacy")

    # ── Flow 7: Explicit commands ──
    print("\n\n### FLOW 7: EXPLICIT COMMANDS ###")
    await send("find")
    await send("near me")
    await send("saved")

    # ── Flow 8: Rate flow ──
    print("\n\n### FLOW 8: RATE FLOW ###")
    # First search and select to have a viewing_pharmacy
    await send("paracetamol")
    await send("1")
    await send("rate 5")
    await send("Great service!")  # comment

    # ── Flow 9: Save flow ──
    print("\n\n### FLOW 9: SAVE FLOW ###")
    await send("paracetamol")
    await send("1")
    await send("save")

    # ── Flow 10: Location ──
    print("\n\n### FLOW 10: LOCATION ###")
    await send("https://maps.google.com/?q=-17.7847594,31.0510115")

    # ── Flow 11: Edge cases ──
    print("\n\n### FLOW 11: EDGE CASES ###")
    await send("back")
    await send("HELP")
    await send("Hello")

    print("\n\n" + "✅ " * 20)
    print("SIMULATION COMPLETE")
    print("✅ " * 20)


if __name__ == "__main__":
    import io, os
    log_path = os.path.join(os.path.dirname(__file__), "sim_output.txt")
    tee = open(log_path, "w", encoding="utf-8")
    _orig_print = print
    def print(*args, **kwargs):
        _orig_print(*args, **kwargs)
        kwargs["file"] = tee
        _orig_print(*args, **kwargs)
        tee.flush()
    import builtins
    builtins.print = print
    asyncio.run(run_all_flows())
    tee.close()
