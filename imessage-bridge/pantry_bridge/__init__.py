"""Pantry Assist iMessage bridge package.

Provides:
  • CommandHandler — routes messages to the OpenClaw agent (agent-first)
    with deterministic offline fallback
  • OpenClawClient / PantryClient — async clients
  • parser helpers (parse_add_command, infer_category, ...)
"""

from pantry_bridge.clients import OpenClawClient, PantryClient
from pantry_bridge.config import (
    ALLOWED_CONTACTS,
    DB_PATH,
    DEDUP_WINDOW_SECONDS,
    LOCK_FILE,
    OPENCLAW_WS,
    PANTRY_API,
    POLL_INTERVAL,
)
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
from pantry_bridge.parser import (
    CATEGORY_DEFAULT_LOCATION,
    CATEGORY_RULES,
    FILLER_WORDS,
    ParsedItem,
    _extract_location_id,
    infer_category,
    normalize_phone,
    parse_add_command,
)

__all__ = [
    "ALLOWED_CONTACTS",
    "CATEGORY_DEFAULT_LOCATION",
    "CATEGORY_RULES",
    "DB_PATH",
    "DEDUP_WINDOW_SECONDS",
    "FILLER_WORDS",
    "LOCK_FILE",
    "OPENCLAW_WS",
    "PANTRY_API",
    "POLL_INTERVAL",
    "CommandHandler",
    "OpenClawClient",
    "PantryClient",
    "ParsedItem",
    "_extract_location_id",
    "acquire_singleton_lock",
    "get_chat_id_for_contact",
    "get_last_message",
    "infer_category",
    "is_duplicate_standalone",
    "normalize_phone",
    "parse_add_command",
    "send_imessage",
    "stop_running_bridge",
]
