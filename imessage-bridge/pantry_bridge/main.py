"""Bridge entrypoint: main loop, chat resolution, self-test, CLI dispatch."""

import asyncio
import sys

from pantry_bridge import config
from pantry_bridge.clients import OpenClawClient, PantryClient
from pantry_bridge.handler import CommandHandler
from pantry_bridge.imessage import (
    get_chat_id_for_contact,
    get_last_message,
    send_imessage,
)
from pantry_bridge.lock import (
    acquire_singleton_lock,
    is_duplicate_standalone,
    stop_running_bridge,
)
from pantry_bridge.parser import normalize_phone, parse_add_command


def resolve_chats() -> dict[str, dict]:
    """Resolve each allowed contact to its chat id + last seen rowid.
    Returns {contact: {"chat_id": str, "last_rowid": int}}."""
    chats: dict[str, dict] = {}
    for contact in config.ALLOWED_CONTACTS:
        chat_id = get_chat_id_for_contact(contact)
        if not chat_id:
            print(f"[Bridge] ⚠️ No chat found for {contact} — skipping")
            continue
        last_rowid = 0
        msg = get_last_message(chat_id)
        if msg:
            last_rowid = msg["rowid"]
        chats[contact] = {"chat_id": chat_id, "last_rowid": last_rowid}
        print(f"[Bridge] {contact} → chat {chat_id} (last rowid {last_rowid})")
    return chats


async def main():
    lock = acquire_singleton_lock()
    if lock is None:
        print("❌ Another bridge instance is already running (see .bridge.pid).")
        print("   Stop it with: python -m pantry_bridge --stop")
        return

    print(f"[Bridge] Allowed contacts: {config.ALLOWED_CONTACTS}")

    # Resolve chat IDs for each allowed contact
    chats = resolve_chats()

    if not chats:
        print(f"❌ No chats found for allowed contacts: {config.ALLOWED_CONTACTS}")
        print("   Check ALLOWED_CONTACTS / IMESSAGE_CONTACT and that iMessage is signed in.")
        return

    pantry = PantryClient(config.PANTRY_API)
    openclaw = OpenClawClient(config.OPENCLAW_WS)
    handler = CommandHandler(pantry, openclaw)

    await openclaw.connect()

    recent_messages = {}  # (contact, text_hash) -> timestamp

    for contact in chats:
        send_imessage(contact, "🥫 Pantry Assist bridge online. Type 'help' for commands.")

    while True:
        try:
            await asyncio.sleep(config.POLL_INTERVAL)
            # Re-resolve periodically so contacts who weren't in iMessage at
            # startup (e.g. a new email chat) get picked up without a restart.
            for contact in config.ALLOWED_CONTACTS:
                if contact not in chats:
                    chat_id = get_chat_id_for_contact(contact)
                    if chat_id:
                        msg = get_last_message(chat_id)
                        last_rowid = msg["rowid"] if msg else 0
                        chats[contact] = {"chat_id": chat_id, "last_rowid": last_rowid}
                        print(f"[Bridge] {contact} → chat {chat_id} (last rowid {last_rowid})")
                        send_imessage(contact, "🥫 Pantry Assist bridge online. Type 'help' for commands.")
            for contact, state in chats.items():
                chat_id = state["chat_id"]
                msg = get_last_message(chat_id, state["last_rowid"])
                if not msg or msg["rowid"] <= state["last_rowid"] or msg["is_from_me"]:
                    continue
                state["last_rowid"] = msg["rowid"]
                # Allowlist check: verify the sender actually is the allowed contact
                if normalize_phone(msg["sender"]) != normalize_phone(contact):
                    print(f"[Bridge] Ignoring message from unlisted sender {msg['sender']}")
                    continue
                if is_duplicate_standalone(recent_messages, contact, msg["text"]):
                    print(f"[Bridge] Duplicate ignored: {msg['text'][:40]}")
                    continue
                print(f"[Bridge] [{contact}] New message: {msg['text']}")
                response = await handler.handle(msg["text"], contact=contact)
                send_imessage(contact, response)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Bridge] Error: {e}")

    for contact in chats:
        send_imessage(contact, "🥫 Pantry Assist bridge offline.")
    await pantry.client.aclose()


# ─── Self-test mode ────────────────────────────────────────────
def run_selftest():
    print("=" * 60)
    print("parse_add_command self-tests")
    print("=" * 60)
    cases = [
        "add spinach of 1 bunch",
        "buy 2kg potatoes",
        "add 2L milk expires friday",
        "add 1 bunch of coriander to the fridge",
        "add 500g paneer to fridge",
        "add 1 jar of pickle",
        "please add 3 onions",
        "add 2 tsp turmeric",
        "add 1L coconut oil to pantry",
        "add frozen peas 500g to freezer",
        "add 1 bunch methi expires tomorrow",
        "add some curry leaves",
        "add 6 bananas",
    ]
    for case in cases:
        p = parse_add_command(case)
        status = "❌ ERROR: " + p.error if p.error else "OK"
        detail = f"name='{p.name}' qty={p.quantity} unit={p.unit} cat={p.category} loc={p.location_id} exp={p.expiry_date}"
        print(f"  {case!r}\n     → {status} | {detail}")
    print("=" * 60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_selftest()
    elif "--stop" in sys.argv:
        stop_running_bridge()
    else:
        asyncio.run(main())
