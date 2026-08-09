# Pantry Assist

A home pantry manager you control by **text message**. Keep track of what's in your
fridge/freezer/pantry, get expiry alerts, scan barcodes, and get recipe ideas — all by
sending an iMessage to your own Mac.

```
iMessage ──► pantry_bridge (Python package) ──► OpenClaw agent (Claude + MCP tools) ──► FastAPI backend ──► SQLite
```

## Architecture

```
pantry-assist-app/
├── backend/            FastAPI + SQLModel + SQLite (the source of truth)
│   ├── app/
│   │   ├── api/        REST routes (/api/v1) + agent routes
│   │   ├── services/   barcode (Open Food Facts), agent (recipe gen / expiry)
│   │   ├── models/     SQLModel + Pydantic schemas
│   │   └── templates/  optional web UI (Jinja2)
│   ├── tests/          pytest + TestClient
│   ├── scripts/seed.py      Indian/Idli-Dosa demo data
├── imessage-bridge/    macOS iMessage bridge + MCP server
│   ├── pantry_bridge/      bridge package: config, parser, imessage, clients, handler, main
│   ├── pantry_mcp.py       MCP stdio server → 12 pantry tools for the agent
│   ├── tests/              pytest suite
│   ├── scripts/run_bridge.sh  one-shot launcher
│   └── legacy/             superseded AppleScript bridge
└── docker-compose.yml  API + Ollama (local LLM for the in-app agent)
```

### How a message flows

1. You text an allowed number/email.
2. `pantry_bridge` reads the new row from `~/Library/Messages/chat.db`, checks the
   allowlist, dedupes.
3. It steers OpenClaw: `openclaw agent --session-key pantry-bridge-<contact> --message "<text>"`.
4. Claude decides which MCP tool to call (e.g. `add_item`, `list_items`, `scan_barcode`).
5. `pantry_mcp.py` calls the FastAPI backend at `http://127.0.0.1:8000/api/v1`.
6. The backend persists to SQLite and returns a result; the reply goes back via iMessage.

If OpenClaw/Claude is unavailable, the bridge falls back to a built-in **deterministic
parser** (regex) so the basics (`add`, `list`, `find`, `expiring`, `recipes`) still work offline.

---

## Capabilities (all implemented)

### iMessage Bridge
- Phone/email **allowlist** — only listed senders can control the pantry.
- **Agent-first routing** — every message goes to Claude + MCP; deterministic parser is
  only the offline fallback.
- Singleton lock + `--stop` flag — never two bridges double-replying.
- Duplicate-message detection, periodic re-resolution of new chats/contacts.

### MCP tools available to the agent (`pantry_mcp.py`, registered as server `pantry`)
| Tool | What it does |
|------|--------------|
| `list_locations` | All storage locations (Fridge=1, Freezer=2, Pantry=3, Spice Rack=4, Idli-Dosa Kit=5) |
| `list_items` | Filter by location_id / expiring_soon / search / limit |
| `get_item` | One item by id |
| `add_item` | Create item (name, quantity, unit, category, expiry_date, location_id) |
| `update_item` | Patch fields of an existing item |
| `delete_item` | Remove an item by id |
| `scan_barcode` | Real product lookup via Open Food Facts; creates/returns the item |
| `get_expiring` | Items expiring within N days (default 7) |
| `get_expired` | Already-expired items |
| `get_recipes` | Recipe suggestions (optional `meal_type`) |
| `recipe_feedback` | Rate a recipe 1–5 (teaches future suggestions) |
| `trigger_agent` | Run the background agent (recipe generation + expiry checks) |

### Backend REST API (`/api/v1`)
| Resource | Endpoints |
|----------|-----------|
| **Items** | `GET/POST /items`, `GET/PATCH/DELETE /items/{id}`, `POST /items/scan`, `POST /items/bulk-delete` |
| **Locations** | `GET/POST /locations`, `GET/PATCH/DELETE /locations/{id}` |
| **Reminders** | `GET /reminders/expiring?days=7`, `GET /reminders/expired` |
| **Recipes** | `GET /recipes/suggestions?meal_type=`, `POST /recipes/feedback` |
| **Agent** | `POST /agent/run`, `GET /agent/status` |
| **Health** | `GET /health` |

Interactive docs: http://127.0.0.1:8000/docs (Swagger UI).

### Background agent (in backend)
- `AsyncIOScheduler` in the FastAPI lifespan: runs once at startup, then every
  `AGENT_INTERVAL_MINUTES` (default 60).
- Generates recipe suggestions from inventory via a local Ollama model, checks expiry.
- Status via `GET /api/v1/agent/status` → `scheduler_running`, `last_run`, `next_run`.

### Barcode scanning
- `POST /api/v1/items/scan?barcode=<code>` → checks DB → real lookup on
  [Open Food Facts](https://world.openfoodfacts.org) → creates item with the real product
  name/category, or returns the existing one.
- Good for **packaged** goods (EAN-13 barcodes). Loose produce like spinach has no barcode —
  use `add spinach of 1 bunch` instead.

---

## Step-by-step operation

### 0. Prerequisites (one-time)
- macOS, iMessage signed in, Automation permission for your terminal app.
- Python 3.12 (via pyenv), OpenClaw CLI installed, Docker.

### 1. Start the backend (API + local LLM)

```bash
# from repo root — API (port 8000) + Ollama (port 11434)
docker compose up --build -d
```

Or without Docker:

```bash
cd backend
uvicorn app.main:app --reload        # dev, hot reload
```

Verify: `curl http://127.0.0.1:8000/health` → `{"status":"ok",...}`

Seed demo data (optional): `cd backend && python scripts/seed.py`

### 2. Start OpenClaw gateway

```bash
# gateway serves the agent on ws://127.0.0.1:18789
openclaw gateway
```

Check the default model is cloud Claude (most reliable for tool calling):

```bash
openclaw models get                       # expect claude-cli/claude-opus-4-8
openclaw config set models.default claude-cli/claude-opus-4-8
```

### 3. Register the MCP server (one-time)

> Use the **pyenv** python — OpenClaw's LaunchAgent PATH may resolve `python3` to
> `/usr/bin/python3`, which lacks the `mcp` module.

```bash
openclaw mcp unset pantry 2>/dev/null
openclaw mcp add pantry \
  --command "$(which python3)" \
  --arg "$PWD/imessage-bridge/pantry_mcp.py"
openclaw mcp probe pantry     # expect: pantry: 12 tools, resources, prompts
```

### 4. Start the iMessage bridge

```bash
cd imessage-bridge
./scripts/run_bridge.sh      # or: python -m pantry_bridge
```

You should see:
```
[Bridge] Allowed contacts: ...
[Bridge] +1XXXXXXXXXX → chat <id> (last rowid ...)
[iMessage] Sent to +1XXXXXXXXXX: 🥫 Pantry Assist bridge online...
```

Stop it anytime: `python -m pantry_bridge --stop`

### 5. Send a text message and watch it work

Text your own number from a device you control. Watch `bridge.log` / the bridge terminal
for the flow: `New message → chat_agent → MCP tool → reply`.

---

## What to test — query examples

### Add items
| You type | Result |
|----------|--------|
| `add milk` | Adds Milk (qty 1 pcs, auto-categorized Dairy) |
| `add spinach of 1 bunch to fridge` | Adds Spinach, 1 bunch, location Fridge |
| `add 2l milk expires friday` | Adds Milk, 2 l, expiry set to this/next Friday |
| `add palak curry to the fridge and it expires this wednesday` | Adds Palak Curry @ Fridge, expiry Wed (no weekday leaked into the name) |
| `add butter expires in 2 weeks` | Adds Butter, expiry +14 days |
| `add bread expires next friday` | Adds Bread, expiry next Friday |

### Browse / search
| You type | Result |
|----------|--------|
| `list` | Total count + per-location summary, asks which location |
| `list fridge` / `list freezer` / `list pantry` | Items in one spot |
| `find milk` / `where is milk` | Search anywhere |
| `expiring` / `expiring in 3 days` | Items expiring soon |
| `expired` | Items already past expiry |

### Recipes
| You type | Result |
|----------|--------|
| `recipes` / `what can I make for dinner?` | Recipe suggestions from inventory |
| `recipes breakfast` / `recipes dinner` | Filtered by meal type |

### Barcode
| You type | Result |
|----------|--------|
| `scan 5449000000996` | Looks up Coca-Cola on Open Food Facts, adds item, returns real name |

> Vague, conversational, or multi-intent queries work best via Claude/MCP, e.g.
> `what can I make with poha and peanuts?`, `is the milk about to expire?`,
> `I just bought 500g of mozzarella, put it in the fridge`.

### Free-form (handled by Claude, may use any MCP tool)
- `what do I have in the fridge?`
- `anything going bad soon?`
- `rate the last recipe 5 stars`
- `run the agent to refresh suggestions`

### Meta
- `help` — command list
- `categories` — available categories

---

## Configuration

| Variable | Where | Default |
|----------|-------|---------|
| `ALLOWED_CONTACTS` | `scripts/run_bridge.sh` / env | `+1XXXXXXXXXX,+1XXXXXXXXXX,you@example.com` |
| `IMESSAGE_CONTACT` | env (fallback) | `+1XXXXXXXXXX` |
| `OPENCLAW_WS` | env | `ws://127.0.0.1:18789` |
| `PANTRY_API` | env | `http://127.0.0.1:8000/api/v1` |
| `POLL_INTERVAL` | env | `5` |
| `DATABASE_URL` | `backend/.env` | `sqlite:///./data/pantry.db` |
| `OPENAI_BASE_URL` | `backend/.env` | `http://127.0.0.1:11434/v1` (use `127.0.0.1`, not `localhost`) |
| `OPENAI_MODEL` | `backend/.env` | e.g. `gemma3:4b` |
| `AGENT_ENABLED` / `AGENT_INTERVAL_MINUTES` | `backend/.env` | `true` / `60` |

---

## Running tests

```bash
# backend (API + barcode + agent) — expects 30+ tests
cd backend && pytest

# bridge + MCP server — expects 43+ tests
cd imessage-bridge && python3 -m pytest tests/
```

Lint (backend): `cd backend && ruff check .`

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No chat found for <contact>` | iMessage not signed in, or that contact hasn't iMessaged your Mac yet. Send them a message first. |
| Bridge won't start (another instance) | `python -m pantry_bridge --stop` |
| `mcp probe` → `Connection closed` | Use the same Python that has the `mcp` package installed (`which python3` or the pyenv shim path) when adding the server: `openclaw mcp add pantry --command "$(which python3)" --arg "$PWD/imessage-bridge/pantry_mcp.py"`. |
| Agent replies `unavailable` | OpenClaw gateway down → `openclaw gateway`. Fallback parser handles basics. |
| API unreachable | `docker compose up -d` (backend) or `uvicorn` locally; check `curl /health`. |
| Ollama model not found | Pull it: `docker exec pantry-assist-app-ollama-1 ollama pull gemma3:4b`. |
| Item name contains the weekday ("…Wednesday") | Fixed in `parse_add_command` — ensure bridge is on the latest code (restart it). |

## Gotchas
- **Agent-first means ~5–8s replies** for every message (cloud Claude round trip).
  Deterministic fallback is instant but only used when the agent is down.
- Backend **no auth** — for local/trusted networks only.
- `AGENTS.md` in the repo root is the dev-facing spec (architecture, commands, roadmap).
- The in-app background agent runs on startup + every `AGENT_INTERVAL_MINUTES`; you can
  also trigger it manually with `POST /api/v1/agent/run` (requires `DEBUG=true`).
