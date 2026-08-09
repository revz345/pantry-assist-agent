"""Singleton lock + duplicate detection for the bridge."""

import hashlib
import os
from datetime import datetime

from pantry_bridge.config import DEDUP_WINDOW_SECONDS, LOCK_FILE

try:
    import fcntl
except ImportError:
    fcntl = None  # non-POSIX (e.g. Windows) — lock is best-effort


def is_duplicate_standalone(seen: dict, contact: str, text: str,
                            window: int = DEDUP_WINDOW_SECONDS) -> bool:
    """Pure dedup check shared with the main loop. `seen` maps
    (contact, md5(text.lower())) -> datetime of last sighting."""
    text_hash = hashlib.md5(text.strip().lower().encode()).hexdigest()
    key = (contact, text_hash)
    now = datetime.now()
    if key in seen and (now - seen[key]).total_seconds() < window:
        return True
    seen[key] = now
    for k in list(seen.keys()):
        if (now - seen[k]).total_seconds() > window * 2:
            del seen[k]
    return False


def acquire_singleton_lock() -> object | None:
    """Take an exclusive flock on LOCK_FILE so only one bridge runs.
    Returns the lock object (keep it alive for the process lifetime),
    or None if another instance already holds the lock."""
    if fcntl is None:
        return object()
    try:
        lock = open(LOCK_FILE, "a+")  # "a+" doesn't truncate on a failed flock
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.seek(0)
        lock.truncate(0)
        lock.write(str(os.getpid()))
        lock.flush()
        return lock
    except OSError:
        return None


def stop_running_bridge() -> bool:
    """Kill the PID recorded in LOCK_FILE, if any."""
    try:
        with open(LOCK_FILE) as f:
            content = f.read().strip()
        if not content:
            print("No bridge running (empty lock file).")
            return False
        pid = int(content)
        os.kill(pid, 15)
        print(f"Stopped bridge (PID {pid}).")
        return True
    except FileNotFoundError:
        print("No bridge running (no lock file).")
        return False
    except ProcessLookupError:
        print(f"No process with PID {pid} — stale lock file.")
        return False
