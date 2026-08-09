"""Pantry Assist bridge — configuration constants."""

import os

OPENCLAW_WS = os.getenv("OPENCLAW_WS", "ws://127.0.0.1:18789")
PANTRY_API = os.getenv("PANTRY_API", "http://127.0.0.1:8000/api/v1")
# Comma-separated list of phone numbers/emails allowed to control the agent.
# Falls back to IMESSAGE_CONTACT for backward compatibility.
ALLOWED_CONTACTS = [
    c.strip()
    for c in os.getenv(
        "ALLOWED_CONTACTS",
        os.getenv("IMESSAGE_CONTACT", "+1XXXXXXXXXX,you@example.com"),
    ).split(",")
    if c.strip()
]
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "5"))
DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")
DEDUP_WINDOW_SECONDS = 30  # ignore same text within this window

# Singleton lock lives at the package root (imessage-bridge/.bridge.pid)
BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_FILE = os.path.join(BRIDGE_DIR, ".bridge.pid")
