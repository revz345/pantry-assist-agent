"""CommandHandler — routes an iMessage to the OpenClaw agent (agent-first)
with deterministic offline fallback handlers."""


from pantry_bridge.clients import OpenClawClient, PantryClient
from pantry_bridge.parser import CATEGORY_RULES, _extract_location_id, parse_add_command


class CommandHandler:
    def __init__(self, pantry: PantryClient, openclaw: OpenClawClient):
        self.pantry = pantry
        self.openclaw = openclaw
        self.sessions: dict[str, dict] = {}  # contact -> pending conversation state

    async def handle(self, text: str, contact: str = "unknown") -> str:
        text = text.strip()
        lower = text.lower()

        # help stays local (instant, works offline)
        if lower in ["help", "?", "commands"]:
            return self._help()

        # ── Agent-first: MCP/Claude handles every command ──
        # Claude understands vague queries (locations, expiry phrases, typos)
        # far better than the regex parser, and has the pantry MCP tools.
        try:
            reply = await self._forward_to_openclaw(text, contact=contact)
            if reply:
                return reply
        except Exception as e:
            print(f"[Bridge] Agent steering failed ({e}); using deterministic fallback")

        # ── Deterministic fallback (offline-safe) ──
        # Continue an in-progress conversation (state machine)
        if contact in self.sessions:
            session = self.sessions[contact]
            if session.get("awaiting_location"):
                loc_id = _extract_location_id(lower)
                if loc_id:
                    del self.sessions[contact]
                    return await self._list_items_at(loc_id)
                return ("That doesn't look like a location. Try 'fridge', 'freezer', "
                        "'pantry', 'spice', or 'idli'.")

        if lower.startswith("add ") or lower.startswith("buy ") or lower.startswith("please add") or lower.startswith("pls add"):
            return await self._handle_add(lower)
        if any(kw in lower for kw in ["expiring", "going bad", "bad soon", "expire soon"]):
            return await self._handle_expiring(lower)
        if "expired" in lower or "spoiled" in lower:
            return await self._handle_expired()
        if any(kw in lower for kw in ["find ", "search ", "where is", "where's", "where are"]):
            return await self._handle_find(lower)
        if any(kw in lower for kw in ["list", "show", "what do i have", "inventory", "items", "what do we have"]):
            return await self._handle_list(lower, contact=contact)
        if any(kw in lower for kw in ["recipe", "cook", "make", "dinner", "lunch", "breakfast", "snack", "what can i make"]):
            return await self._handle_recipes(lower)
        if "agent" in lower or "run agent" in lower:
            return await self._handle_agent()
        if "categories" in lower or "category" in lower:
            return self._categories()
        return "🤖 OpenClaw unavailable. Try 'help'."

    def _help(self) -> str:
        return """🥫 Pantry Assist Commands:
• "list" - See what's in the pantry (I'll ask which location)
• "list fridge" / "freezer" / "pantry" - Items in a spot
• "find milk" / "where is milk" - Search items anywhere
• "expiring" - Items expiring soon
• "expired" - Already expired items
• "recipes" / "what can I make" - Recipe suggestions
• "recipes breakfast" / "dinner" / "lunch" / "snack" - Filter by meal
• "add spinach of 1 bunch to fridge" - Add item (parses qty/unit/category)
• "run agent" - Trigger background agent
• "help" - This message"""

    def _categories(self) -> str:
        cats = sorted({c for c, _ in CATEGORY_RULES})
        return "🏷️ Categories:\n• " + "\n• ".join(cats)

    async def _handle_expiring(self, text: str) -> str:
        days = 7
        if "3 day" in text or "three day" in text:
            days = 3
        elif "1 day" in text or "one day" in text:
            days = 1
        items = await self.pantry.get_expiring(days)
        if not items:
            return f"✅ No items expiring in {days} days!"
        lines = [f"⚠️ {len(items)} items expiring within {days} days:"]
        for item in items[:10]:
            exp = item.get("expiry_date", "?")
            loc = await self.pantry.location_name(item.get("location_id"))
            lines.append(f"• {item['name']} ({item['quantity']} {item['unit']}) - expires {exp} {loc}")
        return "\n".join(lines)

    async def _handle_expired(self) -> str:
        items = await self.pantry.get_expired()
        if not items:
            return "✅ No expired items!"
        lines = [f"🗑️ {len(items)} expired items:"]
        for item in items[:10]:
            exp = item.get("expiry_date", "?")
            lines.append(f"• {item['name']} ({item['quantity']} {item['unit']}) - expired {exp}")
        return "\n".join(lines)

    async def _handle_list(self, text: str, contact: str = "unknown") -> str:
        loc_id = _extract_location_id(text)
        if loc_id:
            return await self._list_items_at(loc_id)

        # Conversational: show a compact summary, then ask which location
        items = await self.pantry.list_items()
        if not items:
            return "📦 Pantry is empty!"
        by_loc: dict[int | None, int] = {}
        for item in items:
            lid = item.get("location_id")
            by_loc[lid] = by_loc.get(lid, 0) + 1
        summary_parts = []
        for lid, count in sorted(by_loc.items(), key=lambda kv: (kv[0] is None, kv[0])):
            loc_name = await self.pantry.location_name(lid) or "Unassigned"
            summary_parts.append(f"{loc_name} ({count})")
        summary = ", ".join(summary_parts)
        self.sessions[contact] = {"awaiting_location": True}
        return (f"📦 {len(items)} items total.\n📍 By location: {summary}\n\n"
                f"Which location do you want to look at? "
                f"('fridge', 'freezer', 'pantry', 'spice', 'idli')")

    async def _list_items_at(self, loc_id: int) -> str:
        items = await self.pantry.list_items(location_id=loc_id)
        if not items:
            return f"📦 No items in {await self.pantry.location_name(loc_id) or 'that location'}."
        loc_name = await self.pantry.location_name(loc_id) or "that location"
        lines = [f"📦 {len(items)} items in {loc_name}:"]
        for item in items[:20]:
            exp = f" (exp {item['expiry_date']})" if item.get("expiry_date") else ""
            cat = f" [{item['category']}]" if item.get("category") else ""
            lines.append(f"• {item['name']} - {item['quantity']} {item['unit']}{cat}{exp}")
        return "\n".join(lines)

    async def _handle_find(self, text: str) -> str:
        for kw in ["find", "search", "where is", "where's", "where are"]:
            text = text.replace(kw, "")
        query = text.strip(" ?!.：:")
        if not query:
            return "🔍 Find what? Try 'find milk'."
        items = await self.pantry.list_items(search=query)
        if not items:
            return f"🔍 No items matching '{query}'."
        lines = [f"🔍 {len(items)} match(es) for '{query}':"]
        for item in items[:15]:
            exp = f" (exp {item['expiry_date']})" if item.get("expiry_date") else ""
            loc = await self.pantry.location_name(item.get("location_id")) or "?"
            lines.append(f"• {item['name']} - {item['quantity']} {item['unit']} @ {loc}{exp}")
        return "\n".join(lines)

    async def _handle_recipes(self, text: str) -> str:
        meal_type = None
        for mt in ["breakfast", "lunch", "snack", "dinner"]:
            if mt in text:
                meal_type = mt
                break
        recipes = await self.pantry.get_recipes(meal_type=meal_type)
        if not recipes:
            # Try triggering agent to generate fresh suggestions
            await self.pantry.trigger_agent()
            recipes = await self.pantry.get_recipes(meal_type=meal_type)
        if not recipes:
            return f"🍳 No {meal_type or ''} recipes yet. Try 'run agent' to generate."
        label = f" {meal_type}" if meal_type else ""
        lines = [f"🍳 {len(recipes)}{label} recipe suggestions:"]
        for r in recipes[:3]:
            lines.append(f"\n📝 {r['title']}")
            mt = f" · {r['meal_type']}" if r.get("meal_type") else ""
            if r.get("description"):
                lines.append(f"   {r['description']}{mt}")
            if r.get("estimated_time_minutes"):
                lines.append(f"   ⏱️ {r['estimated_time_minutes']} min")
            if r.get("servings"):
                lines.append(f"   👥 {r['servings']} servings")
            if r.get("ingredients"):
                lines.append(f"   🥘 {', '.join(r['ingredients'][:5])}{'...' if len(r['ingredients']) > 5 else ''}")
        return "\n".join(lines)

    async def _handle_add(self, text: str) -> str:
        parsed = parse_add_command(text)
        if parsed.error:
            return f"❌ {parsed.error}\n   Try: 'add 2L milk expires friday' or 'add spinach of 1 bunch to fridge'"

        # Dedupe check: does an item with this name already exist?
        existing = await self.pantry.list_items(search=parsed.name)
        if existing:
            e = existing[0]
            return (f"ℹ️ '{e['name']}' already exists ({e['quantity']} {e['unit']}"
                    f" @ {await self.pantry.location_name(e.get('location_id'))}).\n"
                    f"   Add {parsed.quantity} {parsed.unit} anyway? If not, try a different name.")

        result = await self.pantry.add_item(
            name=parsed.name,
            quantity=parsed.quantity,
            unit=parsed.unit,
            location_id=parsed.location_id,
            category=parsed.category,
            expiry_date=parsed.expiry_date,
        )
        if not result["ok"]:
            return f"❌ Failed to add: {result['body'][:200]}"

        loc = await self.pantry.location_name(parsed.location_id) if parsed.location_id else "no location"
        cat = f" [{parsed.category}]" if parsed.category else ""
        exp = f" expires {parsed.expiry_date}" if parsed.expiry_date else ""
        return (f"✅ Added: {parsed.name} ({parsed.quantity} {parsed.unit}){cat}"
                f" @ {loc}{exp}")

    async def _handle_agent(self) -> str:
        result = await self.pantry.trigger_agent()
        return f"🤖 Agent done: {result.get('result', {})}"

    async def _forward_to_openclaw(self, text: str, contact: str = "unknown") -> str:
        """Steer the OpenClaw agent (MCP tools). Raises on failure so the
        caller can fall back to the deterministic offline handlers.

        Prepends today's date so the agent computes relative dates
        ("tomorrow", "in 2 days") correctly instead of guessing."""
        from datetime import date
        today = date.today().isoformat()  # noqa: DTZ011 — local calendar date is what the user means by "today"
        result = await self.openclaw.chat_agent(f"[Today is {today}] {text}", contact=contact)
        return result or "🤖 (no response)"
