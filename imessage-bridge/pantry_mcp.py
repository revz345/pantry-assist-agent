#!/usr/bin/env python3
"""
Pantry Assist MCP server.

Exposes the Pantry Assist REST API as MCP tools so an agent (e.g. OpenClaw
with Claude) can manage the pantry directly:

  • list_locations         – all storage locations (fridge/freezer/pantry/…)
  • list_items             – filter by location, expiring-soon, or search text
  • get_item               – one item by id
  • add_item               – create an item
  • update_item            – modify quantity/location/category/expiry/…
  • delete_item            – remove an item
  • get_expiring           – items expiring within N days
  • get_expired            – already-expired items
  • get_recipes            – recipe suggestions (optional meal_type)
  • recipe_feedback        – rate a recipe (teaches future suggestions)
  • trigger_agent          – run the in-app background agent (recipe gen/expiry)

Runs over stdio. Register with OpenClaw:

    openclaw mcp set pantry '{"command":"python3","args":["<REPO_ROOT>/imessage-bridge/pantry_mcp.py"]}'
"""

import asyncio
import json
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

PANTRY_API = os.getenv("PANTRY_API", "http://127.0.0.1:8000/api/v1")


def _fmt(item: dict) -> str:
    loc = item.get("location_name") or item.get("location_id") or "?"
    exp = f" · exp {item['expiry_date']}" if item.get("expiry_date") else ""
    cat = f" [{item['category']}]" if item.get("category") else ""
    return f"{item['id']}. {item['name']} — {item['quantity']} {item['unit']}{cat} @ {loc}{exp}"


class Pantry:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._locations: dict[int, str] | None = None

    async def _load_locations(self) -> dict[int, str]:
        if self._locations is None:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.base_url}/locations")
                self._locations = {loc["id"]: loc["name"] for loc in r.json()}
        return self._locations

    async def _decorate(self, items: list[dict]) -> list[dict]:
        locs = await self._load_locations()
        for it in items:
            it["location_name"] = locs.get(it.get("location_id"), "")
        return items

    async def list_locations(self) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/locations")
            locs = r.json()
        if not locs:
            return "No locations configured."
        return "Locations:\n" + "\n".join(
            f"• {loc['id']}. {loc['name']}" + (f" — {loc['description']}" if loc.get("description") else "")
            for loc in locs
        )

    async def list_items(self, location_id: int | None = None,
                         expiring_soon: bool = False, days: int = 7,
                         search: str | None = None, limit: int = 200) -> str:
        params: dict[str, Any] = {"limit": limit}
        if location_id is not None:
            params["location_id"] = location_id
        if expiring_soon:
            params["expiring_soon"] = "true"
            params["days"] = days
        if search:
            params["search"] = search
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/items", params=params)
            items = await self._decorate(r.json())
        if not items:
            return "No items match."
        return f"{len(items)} item(s):\n" + "\n".join(_fmt(i) for i in items)

    async def get_item(self, item_id: int) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/items/{item_id}")
            if r.status_code == 404:
                return f"Item {item_id} not found."
            item = (await self._decorate([r.json()]))[0]
        return _fmt(item)

    async def add_item(self, name: str, quantity: float = 1.0, unit: str = "pcs",
                       category: str | None = None, expiry_date: str | None = None,
                       location_id: int | None = None) -> str:
        payload = {
            "name": name, "quantity": quantity, "unit": unit,
            "category": category, "expiry_date": expiry_date, "location_id": location_id,
        }
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.base_url}/items", json=payload)
            if r.status_code not in (200, 201):
                return f"❌ Failed to add item: {r.status_code} {r.text[:300]}"
            item = (await self._decorate([r.json()]))[0]
        reply = f"✅ Added: {_fmt(item)}"
        # Be loud about what was NOT saved, so the agent reports accurately
        # instead of claiming location/expiry that were never persisted.
        missing = []
        if item.get("location_id") is None:
            missing.append("location")
        if not item.get("expiry_date"):
            missing.append("expiry_date")
        if missing:
            reply += (f"\n⚠️ Actually saved WITHOUT: {', '.join(missing)} "
                      f"(null in DB). If the user specified these, call update_item to set them.")
        return reply

    async def update_item(self, item_id: int, name: str | None = None,
                          quantity: float | None = None, unit: str | None = None,
                          category: str | None = None, expiry_date: str | None = None,
                          location_id: int | None = None) -> str:
        payload = {k: v for k, v in {
            "name": name, "quantity": quantity, "unit": unit,
            "category": category, "expiry_date": expiry_date, "location_id": location_id,
        }.items() if v is not None}
        if not payload:
            return "No fields to update."
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{self.base_url}/items/{item_id}", json=payload)
            if r.status_code == 404:
                return f"Item {item_id} not found."
            item = (await self._decorate([r.json()]))[0]
        return f"✅ Updated: {_fmt(item)}"

    async def delete_item(self, item_id: int) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.delete(f"{self.base_url}/items/{item_id}")
        if r.status_code == 204:
            return f"🗑️ Deleted item {item_id}."
        if r.status_code == 404:
            return f"Item {item_id} not found."
        return f"❌ Delete failed: {r.status_code} {r.text[:200]}"

    async def get_expiring(self, days: int = 7) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/reminders/expiring", params={"days": days})
            items = await self._decorate(r.json())
        if not items:
            return f"✅ No items expiring within {days} days."
        return f"⚠️ {len(items)} item(s) expiring within {days} days:\n" + "\n".join(_fmt(i) for i in items)

    async def get_expired(self) -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/reminders/expired")
            items = await self._decorate(r.json())
        if not items:
            return "✅ No expired items."
        return f"🗑️ {len(items)} expired item(s):\n" + "\n".join(_fmt(i) for i in items)

    async def get_recipes(self, meal_type: str | None = None, limit: int = 3) -> str:
        params = {"limit": limit}
        if meal_type:
            params["meal_type"] = meal_type
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base_url}/recipes/suggestions", params=params)
            recipes = r.json()
        if not recipes:
            return "No recipe suggestions yet. Try trigger_agent to generate some."
        lines = [f"🍳 {len(recipes)} recipe suggestion(s):"]
        for rec in recipes[:limit]:
            lines.append(f"\n📝 {rec['title']}")
            mt = f" · {rec['meal_type']}" if rec.get("meal_type") else ""
            if rec.get("description"):
                lines.append(f"   {rec['description']}{mt}")
            if rec.get("estimated_time_minutes"):
                lines.append(f"   ⏱️ {rec['estimated_time_minutes']} min")
            if rec.get("servings"):
                lines.append(f"   👥 {rec['servings']} servings")
            if rec.get("ingredients"):
                lines.append(f"   🥘 {', '.join(rec['ingredients'][:6])}")
        return "\n".join(lines)

    async def recipe_feedback(self, recipe_id: int, rating: int,
                              comment: str | None = None, accepted: bool = False) -> str:
        payload = {"recipe_id": recipe_id, "rating": rating, "comment": comment, "accepted": accepted}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.base_url}/recipes/feedback", json=payload)
        if r.status_code in (200, 201):
            return f"✅ Thanks! Recorded rating {rating}/5 for recipe {recipe_id}."
        return f"❌ Feedback failed: {r.status_code} {r.text[:200]}"

    async def trigger_agent(self) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base_url}/agent/run")
        if r.status_code == 200:
            return f"🤖 Agent run complete: {json.dumps(r.json())[:200]}"
        return f"❌ Agent run failed: {r.status_code} {r.text[:200]}"

    async def scan_barcode(self, barcode: str) -> str:
        """Scan a barcode: creates or returns the item, using Open Food Facts."""
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base_url}/items/scan", params={"barcode": barcode})
        if r.status_code != 200:
            return f"❌ Scan failed: {r.status_code} {r.text[:200]}"
        item = (await self._decorate([r.json()]))[0]
        return f"📦 Scanned: {_fmt(item)}"


pantry = Pantry(PANTRY_API)
server = MCPServer(name="pantry-assist", version="1.0.0")


@server.tool(
    name="list_locations",
    title="List storage locations",
    description="List all pantry storage locations (Fridge, Freezer, Pantry, Spice Rack, Idli-Dosa Kit, etc.) with their ids.",
)
async def list_locations() -> str:
    return await pantry.list_locations()


@server.tool(
    name="list_items",
    title="List pantry items",
    description=(
        "List items in the pantry. Filter by location_id (Fridge=1, Freezer=2, Pantry=3, Spice Rack=4, "
        "Idli-Dosa Kit=5), expiring_soon (+days), or search text. Returns up to `limit` items (default 200, "
        "which covers a full pantry). Use this to see what's on hand, check an item exists, or answer 'what do I have'."
    ),
)
async def list_items(
    location_id: int | None = None,
    expiring_soon: bool = False,
    days: int = 7,
    search: str | None = None,
    limit: int = 200,
) -> str:
    return await pantry.list_items(location_id=location_id, expiring_soon=expiring_soon,
                                   days=days, search=search, limit=limit)


@server.tool(
    name="get_item",
    title="Get one item",
    description="Get a single pantry item by its id.",
)
async def get_item(item_id: int) -> str:
    return await pantry.get_item(item_id)


@server.tool(
    name="add_item",
    title="Add an item",
    description=(
        "Add a new item to the pantry. Provide a clean item name, quantity, unit (g/kg/l/ml/pcs/cup/tbsp/tsp), "
        "optional category, optional expiry_date (YYYY-MM-DD), and optional location_id "
        "(see list_locations — 1 Fridge, 2 Freezer, 3 Pantry, 4 Spice Rack, 5 Idli-Dosa Kit)."
    ),
)
async def add_item(
    name: str,
    quantity: float = 1.0,
    unit: str = "pcs",
    category: str | None = None,
    expiry_date: str | None = None,
    location_id: int | None = None,
) -> str:
    return await pantry.add_item(name=name, quantity=quantity, unit=unit,
                                 category=category, expiry_date=expiry_date, location_id=location_id)


@server.tool(
    name="update_item",
    title="Update an item",
    description="Update one or more fields of an existing item (name, quantity, unit, category, expiry_date, location_id).",
)
async def update_item(
    item_id: int,
    name: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    category: str | None = None,
    expiry_date: str | None = None,
    location_id: int | None = None,
) -> str:
    return await pantry.update_item(item_id=item_id, name=name, quantity=quantity, unit=unit,
                                    category=category, expiry_date=expiry_date, location_id=location_id)


@server.tool(
    name="delete_item",
    title="Delete an item",
    description="Delete an item from the pantry by id.",
)
async def delete_item(item_id: int) -> str:
    return await pantry.delete_item(item_id)


@server.tool(
    name="scan_barcode",
    title="Scan a barcode",
    description=(
        "Scan a product barcode: creates a new pantry item (with the real product name "
        "from Open Food Facts) or returns the existing item if already in the pantry."
    ),
)
async def scan_barcode(barcode: str) -> str:
    return await pantry.scan_barcode(barcode)


@server.tool(
    name="get_expiring",
    title="Items expiring soon",
    description="List items that expire within a number of days (default 7). Good for expiry reminders.",
)
async def get_expiring(days: int = 7) -> str:
    return await pantry.get_expiring(days)


@server.tool(
    name="get_expired",
    title="Expired items",
    description="List items whose expiry date has already passed.",
)
async def get_expired() -> str:
    return await pantry.get_expired()


@server.tool(
    name="get_recipes",
    title="Recipe suggestions",
    description="Get recipe suggestions based on current inventory. Optionally filter by meal_type: breakfast, lunch, snack, dinner.",
)
async def get_recipes(meal_type: str | None = None, limit: int = 3) -> str:
    return await pantry.get_recipes(meal_type=meal_type, limit=limit)


@server.tool(
    name="recipe_feedback",
    title="Rate a recipe",
    description="Record a rating (1-5) for a recipe suggestion, which helps improve future suggestions.",
)
async def recipe_feedback(recipe_id: int, rating: int, comment: str | None = None, accepted: bool = False) -> str:
    return await pantry.recipe_feedback(recipe_id=recipe_id, rating=rating, comment=comment, accepted=accepted)


@server.tool(
    name="trigger_agent",
    title="Run background agent",
    description="Trigger the in-app background agent to generate fresh recipe suggestions and check expiry alerts.",
)
async def trigger_agent() -> str:
    return await pantry.trigger_agent()


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
