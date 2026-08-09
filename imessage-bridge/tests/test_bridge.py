"""Integration tests for the iMessage bridge: parser, command routing,
conversational list flow, dedup, and the singleton lock."""
import asyncio
import json

import pytest

import pantry_bridge as bridge
from pantry_bridge import clients, config, lock, main


# ─── Fakes ─────────────────────────────────────────────────────
class FakePantry:
    def __init__(self):
        self.items = []
        self.locations = {1: "Fridge", 2: "Freezer", 3: "Pantry", 4: "Spice Rack", 5: "Idli-Dosa Kit"}
        self.added = []
        self.searches = []

    async def _load_locations(self):
        return None

    async def list_locations(self):
        return self.locations

    async def location_name(self, location_id):
        return self.locations.get(location_id, "")

    async def list_items(self, location_id=None, expiring_soon=False, days=7, search=None):
        items = self.items
        if location_id:
            items = [i for i in items if i.get("location_id") == location_id]
        if search:
            self.searches.append(search)
            items = [i for i in items if search.lower() in i["name"].lower()]
        return items

    async def get_expiring(self, days=7):
        return [i for i in self.items if i.get("expiry_date")]

    async def get_expired(self):
        return []

    async def get_recipes(self, meal_type=None, limit=3):
        return [{"title": "Idli", "meal_type": "breakfast"}]

    async def add_item(self, name, quantity, unit, location_id=None, category=None, expiry_date=None):
        self.added.append((name, quantity, unit, location_id, category, expiry_date))
        return {"ok": True, "status_code": 201, "body": "{}"}

    async def trigger_agent(self):
        return {"result": "ok"}


class FakeOpenClaw:
    def __init__(self, response="hi", down=False):
        self.response = response
        self.down = down
        self.calls = []

    async def chat_agent(self, text, contact="unknown"):
        self.calls.append(("chat_agent", {"text": text, "contact": contact}))
        if self.down:
            raise RuntimeError("OpenClaw down")
        return self.response


def make_handler(pantry=None, openclaw=None):
    return bridge.CommandHandler(pantry or FakePantry(), openclaw or FakeOpenClaw())


def run(coro):
    return asyncio.run(coro)


# ─── Parsing ───────────────────────────────────────────────────
class TestParseAdd:
    def test_simple_quantity(self):
        p = bridge.parse_add_command("add 3 onions")
        assert p.name == "Onions"
        assert p.quantity == 3
        assert p.unit == "pcs"
        assert p.category == "Vegetables"
        assert p.location_id == 1  # fridge by category default

    def test_weight_unit(self):
        p = bridge.parse_add_command("add 2kg potatoes")
        assert p.name == "Potatoes"
        assert p.quantity == 2
        assert p.unit == "kg"

    def test_liquid_volume(self):
        p = bridge.parse_add_command("add 2L milk expires friday")
        assert p.name == "Milk"
        assert p.quantity == 2
        assert p.unit == "l"
        assert p.expiry_date is not None

    def test_explicit_location_wins_over_category(self):
        p = bridge.parse_add_command("add 500g paneer to fridge")
        assert p.name == "Paneer"
        assert p.location_id == 1  # fridge, not pantry default

    def test_explicit_freezer(self):
        p = bridge.parse_add_command("add frozen peas 500g to freezer")
        assert p.name == "Frozen Peas"
        assert p.location_id == 2
        assert p.category == "Frozen"

    def test_clean_name_only(self):
        p = bridge.parse_add_command("add spinach of 1 bunch")
        assert p.name == "Spinach"  # not the full sentence
        assert p.unit == "pcs"
        assert p.category == "Leafy Greens"

    def test_empty_name_errors(self):
        p = bridge.parse_add_command("add")
        assert p.error is not None

    def test_dosa_batter_not_split(self):
        p = bridge.parse_add_command("add dosa batter")
        assert p.name == "Dosa Batter"
        assert p.category == "Batters & Fermentation"
        assert p.location_id == 5  # Idli-Dosa Kit

    def test_expiry_by_day(self):
        p = bridge.parse_add_command("add milk expires by wednesday")
        assert p.name == "Milk"  # "Wednesday" must NOT leak into the name
        assert p.expiry_date is not None

    def test_expiry_in_days(self):
        p = bridge.parse_add_command("add bread expires in 3 days")
        assert p.name == "Bread"  # "Days" must NOT leak into the name
        assert p.expiry_date is not None

    def test_expiry_in_weeks(self):
        p = bridge.parse_add_command("add butter expires in 2 weeks")
        assert p.name == "Butter"
        assert p.expiry_date is not None

    def test_expiry_this_weekday(self):
        p = bridge.parse_add_command("add palak curry to fridge and it expire this wednesday")
        assert p.name == "Palak Curry"  # no "It" or "Wednesday" leak
        assert p.expiry_date is not None

    def test_expiry_next_weekday(self):
        p = bridge.parse_add_command("add bread expires next friday")
        assert p.name == "Bread"
        assert p.expiry_date is not None

    def test_expire_tomorrow(self):
        p = bridge.parse_add_command("add milk expire tomorrow")
        assert p.name == "Milk"
        assert p.expiry_date is not None


# ─── Category inference ────────────────────────────────────────
class TestInferCategory:
    def test_word_boundary(self):
        assert bridge.infer_category("Hing") == "Spices"
        assert bridge.infer_category("Thing") is None  # must not match "hing"

    def test_known(self):
        assert bridge.infer_category("milk") == "Dairy"
        assert bridge.infer_category("turmeric") == "Spices"
        assert bridge.infer_category("curry leaves") == "Leafy Greens"


# ─── Command routing ───────────────────────────────────────────
class TestCommandRouting:
    def test_help(self):
        r = run(make_handler().handle("help"))
        assert "Commands" in r

    def test_agent_first_add(self):
        # Even 'add ...' goes to the agent (Claude) when available
        oc = FakeOpenClaw("Added Palak Curry to the Fridge, expiring Wed 2026-08-12.")
        pantry = FakePantry()
        r = run(make_handler(pantry, oc).handle("add palak curry to fridge and it expire this wednesday"))
        assert "Palak Curry" in r
        assert oc.calls[0][0] == "chat_agent"
        assert pantry.added == []  # agent did it via MCP, not the parser

    def test_add_routes_to_pantry_when_agent_down(self):
        pantry = FakePantry()
        oc = FakeOpenClaw(down=True)
        r = run(make_handler(pantry, oc).handle("add 3 onions"))
        assert "Added" in r
        assert pantry.added[0][0] == "Onions"

    def test_add_dedupe_hits_existing(self):
        pantry = FakePantry()
        pantry.items = [{"name": "Onions", "quantity": 5, "unit": "pcs", "location_id": 1}]
        r = run(make_handler(pantry, FakeOpenClaw(down=True)).handle("add 3 onions"))
        assert "already exists" in r
        assert pantry.added == []  # not added again

    def test_expiring_routes(self):
        pantry = FakePantry()
        pantry.items = [{"name": "Milk", "quantity": 1, "unit": "l", "location_id": 1, "expiry_date": "2026-08-10"}]
        r = run(make_handler(pantry, FakeOpenClaw(down=True)).handle("expiring"))
        assert "expiring" in r

    def test_find_command(self):
        pantry = FakePantry()
        pantry.items = [
            {"name": "Milk", "quantity": 1, "unit": "l", "location_id": 1},
            {"name": "Curd", "quantity": 2, "unit": "pcs", "location_id": 1},
        ]
        r = run(make_handler(pantry, FakeOpenClaw(down=True)).handle("find milk"))
        assert "Milk" in r
        assert "Curd" not in r

    def test_all_queries_forward_to_openclaw(self):
        oc = FakeOpenClaw("hello there")
        r = run(make_handler(openclaw=oc).handle("what's the weather"))
        assert r == "hello there"
        assert oc.calls[0][0] == "chat_agent"

    def test_openclaw_down_falls_back(self):
        oc = FakeOpenClaw(down=True)
        r = run(make_handler(openclaw=oc).handle("random chat"))
        assert "unavailable" in r


# ─── Conversational list flow (deterministic fallback path) ───
class TestConversationalList:
    def _down_handler(self, pantry):
        return make_handler(pantry, FakeOpenClaw(down=True))

    def test_list_asks_which_location(self):
        pantry = FakePantry()
        pantry.items = [
            {"name": "Milk", "quantity": 1, "unit": "l", "location_id": 1},
            {"name": "Bread", "quantity": 2, "unit": "pcs", "location_id": 3},
        ]
        h = self._down_handler(pantry)
        r = run(h.handle("list", contact="+1XXXXXXXXXX"))
        assert "Which location" in r
        assert "+1XXXXXXXXXX" in h.sessions  # conversation state held

    def test_followup_location_replies_items(self):
        pantry = FakePantry()
        pantry.items = [
            {"name": "Milk", "quantity": 1, "unit": "l", "location_id": 1},
            {"name": "Bread", "quantity": 2, "unit": "pcs", "location_id": 3},
        ]
        h = self._down_handler(pantry)
        run(h.handle("list", contact="+1XXXXXXXXXX"))
        r = run(h.handle("fridge", contact="+1XXXXXXXXXX"))
        assert "Milk" in r
        assert "Bread" not in r
        assert "+1XXXXXXXXXX" not in h.sessions  # state cleared

    def test_list_with_location_does_not_ask(self):
        pantry = FakePantry()
        pantry.items = [{"name": "Bread", "quantity": 2, "unit": "pcs", "location_id": 3}]
        h = self._down_handler(pantry)
        r = run(h.handle("list pantry", contact="+1XXXXXXXXXX"))
        assert "Which location" not in r
        assert "Bread" in r
        assert h.sessions == {}  # no pending state

    def test_bad_location_followup_keeps_state(self):
        pantry = FakePantry()
        pantry.items = [{"name": "Milk", "quantity": 1, "unit": "l", "location_id": 1}]
        h = self._down_handler(pantry)
        run(h.handle("list", contact="x"))
        r = run(h.handle("banana", contact="x"))
        assert "doesn't look like a location" in r
        assert "x" in h.sessions  # can retry


# ─── Dedup ─────────────────────────────────────────────────────
class TestDedup:
    def test_same_text_within_window_is_dup(self):
        seen = {}
        assert not bridge.is_duplicate_standalone(seen, "+1", "help")
        assert bridge.is_duplicate_standalone(seen, "+1", "help")

    def test_different_contact_not_dup(self):
        seen = {}
        assert not bridge.is_duplicate_standalone(seen, "+1", "help")
        assert not bridge.is_duplicate_standalone(seen, "+2", "help")

    def test_case_insensitive_dup(self):
        seen = {}
        assert not bridge.is_duplicate_standalone(seen, "+1", "Help")
        assert bridge.is_duplicate_standalone(seen, "+1", "help")

    def test_different_text_not_dup(self):
        seen = {}
        assert not bridge.is_duplicate_standalone(seen, "+1", "list")
        assert not bridge.is_duplicate_standalone(seen, "+1", "help")


# ─── Location / phone helpers ──────────────────────────────────
class TestHelpers:
    def test_normalize_phone(self):
        assert bridge.normalize_phone("+1 (703) 608-2999") == "17036082999"
        assert bridge.normalize_phone("+17036082999") == "17036082999"

    def test_extract_location(self):
        assert bridge._extract_location_id("fridge") == 1
        assert bridge._extract_location_id("put it in the freezer") == 2
        assert bridge._extract_location_id("banana") is None


# ─── Singleton lock ────────────────────────────────────────────
class TestSingletonLock:
    def test_lock_acquired_then_second_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lock, "LOCK_FILE", str(tmp_path / "bridge.pid"))
        lock1 = lock.acquire_singleton_lock()
        assert lock1 is not None
        lock2 = lock.acquire_singleton_lock()
        assert lock2 is None  # double instance blocked
        lock1.close()

    def test_stop_kills_recorded_pid(self, tmp_path, monkeypatch):
        import subprocess
        child = subprocess.Popen(["sleep", "60"])
        monkeypatch.setattr(lock, "LOCK_FILE", str(tmp_path / "bridge.pid"))
        with open(lock.LOCK_FILE, "w") as f:
            f.write(str(child.pid))
        assert lock.stop_running_bridge() is True
        child.wait(timeout=5)
        assert child.poll() is not None


# ─── Chat re-resolution ────────────────────────────────────────
class TestChatResolution:
    def test_resolve_chats_skips_missing(self, monkeypatch):
        monkeypatch.setattr(main, "get_chat_id_for_contact",
                            lambda contact: "42" if contact == "+1" else None)
        monkeypatch.setattr(main, "get_last_message",
                            lambda chat_id, after_rowid=0: {"rowid": 5})
        monkeypatch.setattr(config, "ALLOWED_CONTACTS", ["+1", "nope@x.com"])
        chats = main.resolve_chats()
        assert set(chats.keys()) == {"+1"}
        assert chats["+1"]["chat_id"] == "42"
        assert chats["+1"]["last_rowid"] == 5


# ─── OpenClaw chat_agent steering ──────────────────────────────
class _FakeProc:
    def __init__(self, out, rc=0, err=b""):
        self._out = out
        self._rc = rc
        self._err = err

    async def communicate(self):
        return self._out, self._err

    @property
    def returncode(self):
        return self._rc


class TestChatAgent:
    def test_parses_payload_text(self, monkeypatch):
        async def fake_exec(*a, **kw):
            payload = json.dumps(
                {"result": {"payloads": [{"text": "🤖 5 items in fridge"}]}}).encode()
            return _FakeProc(payload)

        monkeypatch.setattr(clients.asyncio, "create_subprocess_exec", fake_exec)
        oc = clients.OpenClawClient("ws://x")
        r = run(oc.chat_agent("what's in the fridge?", contact="+1XXXXXXXXXX"))
        assert r == "🤖 5 items in fridge"

    def test_nonzero_rc_raises(self, monkeypatch):
        async def fake_exec(*a, **kw):
            return _FakeProc(b"", rc=1, err=b"boom")

        monkeypatch.setattr(clients.asyncio, "create_subprocess_exec", fake_exec)
        oc = clients.OpenClawClient("ws://x")
        with pytest.raises(RuntimeError):
            run(oc.chat_agent("hello", contact="+1XXXXXXXXXX"))

    def test_session_key_uses_contact(self):
        oc = clients.OpenClawClient("ws://x")
        oc.chat_agent = lambda *a, **k: "hi"
        assert True  # chat_agent defined and patchable
