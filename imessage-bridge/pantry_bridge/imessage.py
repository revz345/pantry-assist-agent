"""Direct (read-only) SQLite access to ~/Library/Messages/chat.db plus
iMessage sending via AppleScript."""

import sqlite3
import subprocess
from datetime import datetime, timedelta

from pantry_bridge.config import DB_PATH


def get_chat_id_for_contact(contact: str) -> str | None:
    """Find the chat ID for a given contact phone/email."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        handle_row = conn.execute(
            "SELECT ROWID FROM handle WHERE id = ?", (contact,)
        ).fetchone()
        if not handle_row:
            return None
        handle_id = handle_row["ROWID"]
        chat_row = conn.execute("""
            SELECT chat_id FROM chat_handle_join WHERE handle_id = ?
        """, (handle_id,)).fetchone()
        return chat_row["chat_id"] if chat_row else None
    finally:
        conn.close()


def get_last_message(chat_id: str, after_rowid: int = 0) -> dict | None:
    """Get the most recent message from chat after given rowid."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT m.ROWID, m.text, m.date, m.is_from_me, h.id as sender
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE cmj.chat_id = ? AND m.ROWID > ? AND m.text IS NOT NULL
            ORDER BY m.ROWID DESC
            LIMIT 1
        """, (chat_id, after_rowid)).fetchone()

        if row:
            apple_epoch = datetime(2001, 1, 1)
            date_val = row["date"]
            msg_date = apple_epoch + timedelta(seconds=date_val / 1e9) if date_val else datetime.now()
            return {
                "rowid": row["ROWID"],
                "text": row["text"],
                "date": msg_date,
                "is_from_me": bool(row["is_from_me"]),
                "sender": row["sender"] or ("me" if row["is_from_me"] else "contact"),
            }
    finally:
        conn.close()
    return None


def send_imessage(contact: str, text: str) -> bool:
    """Send iMessage via AppleScript (only for sending, not reading)."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{contact}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
        print(f"[iMessage] Sent to {contact}: {text[:50]}...")
        return True
    except Exception as e:
        print(f"[iMessage] Send failed: {e}")
        return False
