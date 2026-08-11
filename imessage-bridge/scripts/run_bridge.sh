#!/bin/bash
# Launch script for the iMessage Bridge (pantry_bridge package)
set -e

# Resolve repo root from this script's location so it works wherever you clone it
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BRIDGE_DIR="$REPO_ROOT/imessage-bridge"

# ─── Configuration ─────────────────────────────────────────────
# Comma-separated list of phone numbers/emails allowed to control the agent.
# Only these contacts can send commands.
#
# Resolution order (first match wins):
#   1. $ALLOWED_CONTACTS env var (e.g. set in your shell or CI)
#   2. $BRIDGE_DIR/.bridge.env  (gitignored, holds your real contact)
#
# The placeholders below are safe to commit; replace them locally
# before the bridge will work. See "First-time setup" below.

# First-time setup: create the gitignored .bridge.env with your real contact.
BRIDGE_ENV="$BRIDGE_DIR/.bridge.env"
if [ -z "${ALLOWED_CONTACTS:-}" ] && [ -f "$BRIDGE_ENV" ]; then
    # shellcheck source=/dev/null
    set -a; . "$BRIDGE_ENV"; set +a
fi

if [ -z "${ALLOWED_CONTACTS:-}" ] || [[ "$ALLOWED_CONTACTS" == *"XXXXXXXXXX"* ]] || [[ "$ALLOWED_CONTACTS" == *"you@example.com"* ]]; then
    cat <<EOF >&2
❌ No real contacts configured.

The repo ships with masked placeholders. Before the bridge can deliver
messages you need to set the phone number(s) and/or email that should
be allowed to control the agent.

Quickest setup (one-time, stays on your machine, not committed):

    echo 'ALLOWED_CONTACTS="+1REALNUM1,+1REALNUM2,you@gmail.com"' \\
        > "$BRIDGE_ENV"
    echo 'IMESSAGE_CONTACT="+1REALNUM1"' >> "$BRIDGE_ENV"
    $0

Or just set it in the environment for this run:

    ALLOWED_CONTACTS="+1REALNUM,you@gmail.com" $0

After that the bridge will only respond to messages from those
contacts, and the value is read from .bridge.env on every launch.
EOF
    exit 1
fi

export ALLOWED_CONTACTS
export IMESSAGE_CONTACT="${IMESSAGE_CONTACT:-${ALLOWED_CONTACTS%%,*}}"

# Optional overrides
# export OPENCLAW_WS="ws://127.0.0.1:18789"
# export PANTRY_API="http://127.0.0.1:8000/api/v1"
# export POLL_INTERVAL="5"

# ─── Health checks ─────────────────────────────────────────────
echo "Checking pantry API..."
curl -s http://127.0.0.1:8000/health > /dev/null || {
    echo "Starting pantry API..."
    cd "$REPO_ROOT/backend"
    uvicorn app.main:app --host 0.0.0.0 --port 8000 &
    sleep 3
}

echo "Checking OpenClaw gateway..."
# OpenClaw should already be running from your earlier output

# ─── Start bridge ──────────────────────────────────────────────
cd "$BRIDGE_DIR"

# Stop any previous instance so we never get two bridges double-replying
echo "Stopping any previous bridge instance..."
python -m pantry_bridge --stop || true

echo "Starting iMessage bridge..."
echo "Allowed contacts: $ALLOWED_CONTACTS"
# Unbuffered stdout so the bridge's prints show up in the log immediately
# (when stdout is a pipe/file it's block-buffered by default).
PYTHONUNBUFFERED=1 exec python -u -m pantry_bridge
