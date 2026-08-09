"""Async clients for the OpenClaw gateway and the Pantry API."""

import asyncio
import json
import os

import httpx
import websockets

from pantry_bridge.parser import normalize_phone


# ─── OpenClaw Gateway Client ───────────────────────────────────
class OpenClawClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self.request_id = 0
        self.pending = {}

    async def connect(self):
        try:
            self.ws = await asyncio.wait_for(websockets.connect(self.ws_url), timeout=5)
            print(f"[OpenClaw] Connected to {self.ws_url}")
            asyncio.create_task(self._listen())
        except Exception as e:
            print(f"[OpenClaw] Connection failed: {e}")
            self.ws = None

    async def _listen(self):
        if not self.ws:
            return
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
        if not self.ws:
            raise RuntimeError("Not connected to OpenClaw")
        self.request_id += 1
        req_id = self.request_id
        fut = asyncio.get_event_loop().create_future()
        self.pending[req_id] = fut
        await self.ws.send(json.dumps({
            "id": req_id, "type": "tool_call", "tool": tool_name, "params": params,
        }))
        try:
            response = await asyncio.wait_for(fut, timeout=30)
            return response.get("result", {})
        except asyncio.TimeoutError:
            self.pending.pop(req_id, None)
            raise RuntimeError("Tool call timeout")

    async def chat_agent(self, text: str, contact: str = "unknown") -> str:
        """Steer the OpenClaw agent (which has the pantry MCP tools) with a
        message. Uses a per-contact session key so each chat keeps memory.
        Falls back to the raw WS tool call if the CLI path fails."""
        session_key = f"pantry-bridge-{normalize_phone(contact) or contact.replace('@', '')}"
        env = dict(os.environ)
        cmd = ["openclaw", "agent", "--agent", "main", "--json",
               "--session-key", session_key, "--message", text]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode()[:300])
            data = json.loads(stdout.decode())
            payloads = data.get("result", {}).get("payloads") or []
            if payloads and payloads[0].get("text"):
                return payloads[0]["text"].strip()
            summary = data.get("summary") or data.get("status") or ""
            return f"🤖 (agent: {summary})"
        except Exception as e:
            print(f"[OpenClaw] chat_agent CLI failed ({e}); falling back to WS chat tool")
            try:
                result = await self.call_tool("chat", {"message": text})
                return result.get("response", "🤖 (no response)")
            except Exception:
                raise


# ─── Pantry API Client ─────────────────────────────────────────
class PantryClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30)
        self._locations: dict[int, str] = {}

    async def _load_locations(self):
        if self._locations:
            return
        try:
            r = await self.client.get(f"{self.base_url}/locations")
            for loc in r.json():
                self._locations[loc["id"]] = loc["name"]
        except Exception:
            pass

    async def location_name(self, location_id) -> str:
        await self._load_locations()
        return self._locations.get(location_id, "")

    async def list_locations(self):
        await self._load_locations()
        return self._locations

    async def list_items(self, location_id: int = None, expiring_soon: bool = False, days: int = 7, search: str = None):
        params = {}
        if location_id:
            params["location_id"] = location_id
        if expiring_soon:
            params["expiring_soon"] = "true"
            params["days"] = days
        if search:
            params["search"] = search
        r = await self.client.get(f"{self.base_url}/items", params=params)
        return r.json()

    async def get_expiring(self, days: int = 7):
        r = await self.client.get(f"{self.base_url}/reminders/expiring", params={"days": days})
        return r.json()

    async def get_expired(self):
        r = await self.client.get(f"{self.base_url}/reminders/expired")
        return r.json()

    async def get_recipes(self, meal_type: str = None, limit: int = 3):
        params = {"limit": limit}
        if meal_type:
            params["meal_type"] = meal_type
        r = await self.client.get(f"{self.base_url}/recipes/suggestions", params=params)
        return r.json()

    async def add_item(self, name: str, quantity: float, unit: str, location_id: int = None,
                       category: str = None, expiry_date: str = None) -> dict:
        payload = {
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "location_id": location_id,
            "category": category,
            "expiry_date": expiry_date,
        }
        r = await self.client.post(f"{self.base_url}/items", json=payload)
        return {"ok": r.status_code == 201, "status_code": r.status_code, "body": r.text}

    async def trigger_agent(self):
        r = await self.client.post(f"{self.base_url}/agent/run")
        return r.json()
