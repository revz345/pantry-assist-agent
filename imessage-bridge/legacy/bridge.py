#!/usr/bin/env python3
"""
iMessage ↔ OpenClaw Bridge
Polls iMessage for incoming messages, forwards to OpenClaw gateway, sends replies back.
Requires: macOS, signed into iCloud in Messages, Automation permission for Terminal/Python.
"""

import asyncio
import json
import subprocess
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass

# Add pantry backend to path for API calls
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"))

try:
    import websockets
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "websockets"], check=True)
    import websockets

# ─── Configuration ──────────────────────────────────────────────
OPENCLAW_WS = "ws://127.0.0.1:18789"
PANTRY_API = "http://127.0.0.1:8000/api/v1"
TARGET_CONTACT = os.getenv("IMESSAGE_CONTACT", "+1XXXXXXXXXX")  # Your iMessage address
POLL_INTERVAL = 5  # seconds
LAST_MESSAGE_ID_FILE = "/tmp/imessage_last_id.txt"

# ─── AppleScript Templates ─────────────────────────────────────
APPLESCRIPT_GET_UNREAD = '''
on run {contactPhone, lastDate}
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy contactPhone of targetService
        set msgs to {}
        set chatId to id of chat targetBuddy
        repeat with m in messages of chat chatId
            if date received of m > (date lastDate) then
                if is from me of m is false then
                    set end of msgs to {id: (id of m), text: (text of m), date: (date received of m), sender: (sender of m)}
                end if
            end if
        end repeat
        return msgs
    end tell
end run
'''

APPLESCRIPT_SEND = '''
on run {contactPhone, messageText}
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy contactPhone of targetService
        send messageText to targetBuddy
    end tell
end run
'''

APPLESCRIPT_GET_LATEST = '''
on run {contactPhone}
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy contactPhone of targetService
        set chatId to id of chat targetBuddy
        if (count of messages of chat chatId) > 0 then
            set lastMsg to last message of chat chatId
            set msgId to id of lastMsg
            set msgText to text of lastMsg
            set msgDate to date received of lastMsg
            set msgSender to sender of lastMsg
            return {id: msgId, text: msgText, date: msgDate, sender: msgSender}
        else
            return {}
        end if
    end tell
end run
'''

# ─── Data Classes ──────────────────────────────────────────────
@dataclass
class IMessage:
    id: str
    text: str
    date: datetime
    sender: str

# ─── AppleScript Runner ────────────────────────────────────────
def run_applescript(script: str, args: List[str] = None) -> str:
    """Execute AppleScript and return stdout."""
    cmd = ["osascript", "-e", script]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr}")
    return result.stdout.strip()

def parse_applescript_record(output: str) -> Optional[Dict]:
    """Parse AppleScript record output like {id:"123", text:"hi", date:date \"...\"}"""
    if not output or output == "{}":
        return None
    # Simple parsing for AppleScript record format
    import re
    record = {}
    for key in ["id", "text", "date", "sender"]:
        match = re.search(f'{key}:\\s*"([^"]*)"', output)
        if match:
            record[key] = match.group(1)
    return record if record else None

def get_latest_message(contact: str) -> Optional[IMessage]:
    """Get the most recent message from contact."""
    try:
        output = run_applescript(APPLESCRIPT_GET_LATEST, [contact])
        data = parse_applescript_record(output)
        if data and data.get("text"):
            return IMessage(
                id=data["id"],
                text=data["text"],
                date=datetime.fromisoformat(data["date"].replace("Z", "+00:00")) if "T" in data["date"] else datetime.now(),
                sender=data.get("sender", "")
            )
    except Exception as e:
        print(f"[iMessage] Error getting latest: {e}")
    return None

def send_imessage(contact: str, text: str) -> bool:
    """Send iMessage to contact."""
    try:
        run_applescript(APPLESCRIPT_SEND, [contact, text])
        print(f"[iMessage] Sent to {contact}: {text[:50]}...")
        return True
    except Exception as e:
        print(f"[iMessage] Send failed: {e}")
        return False

# ─── OpenClaw Gateway Client ───────────────────────────────────
class OpenClawClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self.request_id = 0
        self.pending = {}
        
    async def connect(self):
        self.ws = await websockets.connect(self.ws_url)
        print(f"[OpenClaw] Connected to {self.ws_url}")
        asyncio.create_task(self._listen())
        
    async def _listen(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                req_id = data.get("id")
                if req_id in self.pending:
                    fut = self.pending.pop(req_id)
                    fut.set_result(data)
        except Exception as e:
            print(f"[OpenClaw] Listen error: {e}")
            
    async def call_tool(self, tool_name: str, params: dict) -> dict:
        """Call a tool on OpenClaw gateway."""
        if not self.ws:
            raise RuntimeError("Not connected")
        self.request_id += 1
        req_id = self.request_id
        fut = asyncio.get_event_loop().create_future()
        self.pending[req_id] = fut
        
        request = {
            "id": req_id,
            "type": "tool_call",
            "tool": tool_name,
            "params": params
        }
        await self.ws.send(json.dumps(request))
        
        try:
            response = await asyncio.wait_for(fut, timeout=30)
            return response.get("result", {})
        except asyncio.TimeoutError:
            self.pending.pop(req_id, None)
            raise RuntimeError("Tool call timeout")

# ─── Pantry API Client ─────────────────────────────────────────
import httpx

class PantryClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30)
        
    async def list_items(self, location_id: int = None, expiring_soon: bool = False, days: int = 7):
        params = {}
        if location_id: params["location_id"] = location_id
        if expiring_soon: params["expiring_soon"] = "true"; params["days"] = days
        r = await self.client.get(f"{self.base_url}/items", params=params)
        return r.json()
        
    async def get_expiring(self, days: int = 7):
        r = await self.client.get(f"{self.base_url}/reminders/expiring", params={"days": days})
        return r.json()
        
    async def get_expired(self):
        r = await self.client.get(f"{self.base_url}/reminders/expired")
        return r.json()
        
    async def get_recipes(self):
        r = await self.client.get(f"{self.base_url}/recipes/suggestions")
        return r.json()
        
    async def trigger_agent(self):
        r = await self.client.post(f"{self.base_url}/agent/run")
        return r.json()

# ─── Command Handler ───────────────────────────────────────────
class CommandHandler:
    def __init__(self, pantry: PantryClient, openclaw: OpenClawClient):
        self.pantry = pantry
        self.openclaw = openclaw
        
    async def handle(self, text: str) -> str:
        text = text.strip().lower()
        
        # Help
        if text in ["help", "?", "commands"]:
            return self._help()
            
        # Expiring items
        if any(kw in text for kw in ["expir", "expiring", "expire", "going bad", "bad soon"]):
            return await self._handle_expiring(text)
            
        # Expired items
        if "expired" in text or "spoiled" in text:
            return await self._handle_expired()
            
        # Inventory list
        if any(kw in text for kw in ["list", "show", "what do i have", "inventory", "items"]):
            return await self._handle_list(text)
            
        # Recipes
        if any(kw in text for kw in ["recipe", "cook", "make", "dinner", "lunch", "what can i make"]):
            return await self._handle_recipes()
            
        # Add item
        if text.startswith("add ") or text.startswith("buy "):
            return await self._handle_add(text)
            
        # Agent trigger
        if "agent" in text or "run agent" in text:
            return await self._handle_agent()
            
        # Default: forward to OpenClaw for LLM response
        return await self._forward_to_openclaw(text)
        
    def _help(self) -> str:
        return """🥫 Pantry Assist Commands:
• "expiring" / "what's going bad" - Items expiring soon
• "expired" - Already expired items  
• "list" / "inventory" - All items
• "list fridge" - Items in specific location
• "recipes" / "what can I make" - Recipe suggestions
• "add 2L milk expires friday" - Add item
• "run agent" - Trigger background agent
• "help" - This message"""
        
    async def _handle_expiring(self, text: str) -> str:
        days = 7
        if "3 day" in text or "three day" in text:
            days = 3
        elif "1 day" in text or "one day" in text:
            days = 1
            
        items = await self.pantry.get_expiring(days)
        if not items:
            return f"✅ No items expiring in the next {days} days!"
            
        lines = [f"⚠️ {len(items)} items expiring within {days} days:"]
        for item in items[:10]:
            exp = item.get('expiry_date', '?')
            loc = item.get('location', {}).get('name', '') if item.get('location') else ''
            lines.append(f"• {item['name']} ({item['quantity']} {item['unit']}) - expires {exp} {loc}")
        return "\n".join(lines)
        
    async def _handle_expired(self) -> str:
        items = await self.pantry.get_expired()
        if not items:
            return "✅ No expired items!"
        lines = [f"🗑️ {len(items)} expired items:"]
        for item in items[:10]:
            exp = item.get('expiry_date', '?')
            lines.append(f"• {item['name']} ({item['quantity']} {item['unit']}) - expired {exp}")
        return "\n".join(lines)
        
    async def _handle_list(self, text: str) -> str:
        location_id = None
        if "fridge" in text: location_id = 1
        elif "freezer" in text: location_id = 2
        elif "pantry" in text: location_id = 3
        elif "spice" in text: location_id = 4
        elif "idli" in text or "dosa" in text: location_id = 5
        
        items = await self.pantry.list_items(location_id=location_id)
        if not items:
            return "No items found."
            
        lines = [f"📦 {len(items)} items:"]
        for item in items[:20]:
            exp = f" (exp {item['expiry_date']})" if item.get('expiry_date') else ""
            loc = f" @ {item['location']['name']}" if item.get('location') else ""
            lines.append(f"• {item['name']} - {item['quantity']} {item['unit']}{exp}{loc}")
        return "\n".join(lines)
        
    async def _handle_recipes(self) -> str:
        recipes = await self.pantry.get_recipes()
        if not recipes:
            # Try triggering agent to generate
            await self.pantry.trigger_agent()
            recipes = await self.pantry.get_recipes()
            
        if not recipes:
            return "🍳 No recipes yet. Try 'run agent' to generate from current inventory."
            
        lines = [f"🍳 {len(recipes)} recipe suggestions:"]
        for r in recipes[:3]:
            lines.append(f"\n📝 {r['title']}")
            if r.get('description'): lines.append(f"   {r['description']}")
            if r.get('estimated_time_minutes'): lines.append(f"   ⏱️ {r['estimated_time_minutes']} min")
            if r.get('servings'): lines.append(f"   👥 {r['servings']} servings")
            if r.get('ingredients'):
                lines.append(f"   🥘 Ingredients: {', '.join(r['ingredients'][:5])}{'...' if len(r['ingredients'])>5 else ''}")
        return "\n".join(lines)
        
    async def _handle_add(self, text: str) -> str:
        # Simple parsing: "add 2L milk expires friday" or "buy 1kg rice"
        import re
        text = text.replace("add ", "").replace("buy ", "")
        
        # Extract quantity and unit
        qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|l|ml|pcs?|pieces?)', text, re.IGNORECASE)
        quantity = float(qty_match.group(1)) if qty_match else 1
        unit = qty_match.group(2).lower() if qty_match else "pcs"
        if unit == "piece": unit = "pcs"
        
        # Extract expiry
        expiry = None
        exp_match = re.search(r'expires?\s+(\w+)', text, re.IGNORECASE)
        if exp_match:
            day = exp_match.group(1).lower()
            today = datetime.now()
            days_map = {"today": 0, "tomorrow": 1, "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            if day in days_map:
                target = (today.weekday() + days_map[day] + 7) % 7
                if target == 0: target = 7
                expiry = (today + timedelta(days=target)).strftime("%Y-%m-%d")
        
        # Name is the rest
        name = re.sub(r'\d+\.?\d*\s*(kg|g|l|ml|pcs?|pieces?)', '', text, flags=re.IGNORECASE)
        name = re.sub(r'expires?\s+\w+', '', name, flags=re.IGNORECASE).strip()
        if not name:
            return "❌ Could not parse item name. Try: 'add 2L milk expires friday'"
            
        # For simplicity, default to Pantry location (3)
        # In real use, you'd want to specify location
        r = await self.pantry.client.post(f"{self.pantry.base_url}/items", json={
            "name": name, "quantity": quantity, "unit": unit, 
            "location_id": 3, "expiry_date": expiry
        })
        if r.status_code == 201:
            return f"✅ Added: {name} ({quantity} {unit}){' expires ' + expiry if expiry else ''}"
        return f"❌ Failed to add: {r.text}"
        
    async def _handle_agent(self) -> str:
        result = await self.pantry.trigger_agent()
        return f"🤖 Agent cycle complete: {result.get('result', {})}"
        
    async def _forward_to_openclaw(self, text: str) -> str:
        """Forward to OpenClaw for general LLM response."""
        try:
            # This assumes OpenClaw has a chat/completion tool
            result = await self.openclaw.call_tool("chat", {"message": text})
            return result.get("response", "🤖 (no response)")
        except Exception as e:
            return f"🤖 OpenClaw error: {e}. Try 'help' for commands."

# ─── Main Bridge Loop ──────────────────────────────────────────
async def main():
    contact = os.getenv("IMESSAGE_CONTACT")
    if not contact:
        print("❌ Set IMESSAGE_CONTACT env var (your iMessage phone/email)")
        return
        
    print(f"[Bridge] Starting iMessage ↔ OpenClaw bridge")
    print(f"[Bridge] Contact: {contact}")
    print(f"[Bridge] OpenClaw: {OPENCLAW_WS}")
    print(f"[Bridge] Pantry API: {PANTRY_API}")
    
    # Initialize clients
    pantry = PantryClient(PANTRY_API)
    openclaw = OpenClawClient(OPENCLAW_WS)
    handler = CommandHandler(pantry, openclaw)
    
    # Connect to OpenClaw
    try:
        await openclaw.connect()
    except Exception as e:
        print(f"[OpenClaw] Connection failed: {e}")
        print("[Bridge] Continuing without OpenClaw (pantry commands only)")
    
    # Track last processed message
    last_msg = get_latest_message(contact)
    last_id = last_msg.id if last_msg else None
    print(f"[Bridge] Last message ID: {last_id}")
    
    # Send startup message
    send_imessage(contact, "🥫 Pantry Assist bridge online. Type 'help' for commands.")
    
    # Main loop
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            
            # Check for new messages
            current = get_latest_message(contact)
            if current and current.id != last_id:
                print(f"[Bridge] New message: {current.text}")
                last_id = current.id
                
                # Process command
                response = await handler.handle(current.text)
                
                # Send reply
                send_imessage(contact, response)
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Bridge] Error: {e}")
            
    send_imessage(contact, "🥫 Pantry Assist bridge offline.")
    await pantry.client.aclose()

if __name__ == "__main__":
    asyncio.run(main())