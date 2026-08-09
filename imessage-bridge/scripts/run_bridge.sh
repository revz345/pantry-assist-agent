#!/bin/bash
# Launch script for the iMessage Bridge (pantry_bridge package)
set -e

# Resolve repo root from this script's location so it works wherever you clone it
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ─── Configuration ─────────────────────────────────────────────
# Comma-separated list of phone numbers/emails allowed to control the agent.
# Only these contacts can send commands. Example: "+15555550100,+15555550101"
# Override via env:  ALLOWED_CONTACTS="+1XXXXXXXXXX,you@example.com" ./scripts/run_bridge.sh
export ALLOWED_CONTACTS="${ALLOWED_CONTACTS:-+1XXXXXXXXXX,+1XXXXXXXXXX,you@example.com}"

# Backward-compatible: IMESSAGE_CONTACT is used as a fallback if ALLOWED_CONTACTS is empty
export IMESSAGE_CONTACT="${IMESSAGE_CONTACT:-+1XXXXXXXXXX}"

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
cd "$REPO_ROOT/imessage-bridge"

# Stop any previous instance so we never get two bridges double-replying
echo "Stopping any previous bridge instance..."
python -m pantry_bridge --stop || true

echo "Starting iMessage bridge..."
echo "Allowed contacts: $ALLOWED_CONTACTS"
python -m pantry_bridge
