from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from app.api.agent_routes import router as agent_router
from app.api.routes import locations_router, recipes_router, reminders_router
from app.api.routes import router as items_router
from app.core.config import get_settings
from app.db.session import get_session, init_db
from app.models.schemas import Item, Location, RecipeSuggestion

settings = get_settings()

# Custom Jinja2 environment to avoid cache bug
jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
    cache_size=0,  # Disable cache
)

# Display-only unit relabeling (storage stays as-is)
UNIT_LABELS = {"kg": "oz", "l": "qt", "ml": "fl oz"}

ITEM_CATEGORIES = [
    "Leafy Greens",
    "Vegetables",
    "Fruits",
    "Dairy",
    "Chutneys & Pickles",
    "Batters & Fermentation",
    "Grains & Dals",
    "Spices",
    "Oils & Ghee",
    "Frozen",
    "Condiments",
    "Other",
]

MEAL_TYPES = ["breakfast", "lunch", "snack", "dinner"]


def unit_label(value):
    return UNIT_LABELS.get(str(value), str(value))


jinja_env.filters["unit_label"] = unit_label


def render_template(template_name: str, context: dict) -> HTMLResponse:
    template = jinja_env.get_template(template_name)
    return HTMLResponse(template.render(context))


_agent_scheduler: Optional[object] = None
_agent_last_run: Optional[str] = None


def get_agent_scheduler_state() -> dict:
    """Expose the background agent scheduler state (for /agent/status)."""
    state: dict = {"running": False, "last_run": None, "next_run": None}
    if _agent_scheduler is not None:
        state["running"] = _agent_scheduler.running
        state["last_run"] = _agent_last_run
        jobs = getattr(_agent_scheduler, "get_jobs", lambda: [])()
        if jobs:
            state["next_run"] = str(jobs[0].next_run_time)
    return state


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    global _agent_scheduler, _agent_last_run
    scheduler = None
    if settings.agent_enabled:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from app.db.session import SessionLocal
            from app.services.agent import run_agent_cycle

            scheduler = AsyncIOScheduler()

            async def agent_job():
                global _agent_last_run
                with SessionLocal() as session:
                    results = await run_agent_cycle(session)
                    _agent_last_run = datetime.utcnow().isoformat()
                    print(f"[Agent] Periodic cycle: {results}")

            scheduler.add_job(
                agent_job,
                "interval",
                minutes=settings.agent_interval_minutes,
                id="pantry-agent-cycle",
                replace_existing=True,
            )
            scheduler.start()
            _agent_scheduler = scheduler
            print(
                f"[Agent] Auto-start enabled: every {settings.agent_interval_minutes} min "
                f"(run once at startup)"
            )
            await agent_job()  # run immediately at startup
        except Exception as e:
            print(f"[Agent] Scheduler failed to start: {e}")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        _agent_scheduler = None


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# API v1
api_prefix = settings.api_v1_prefix
app.include_router(items_router, prefix=f"{api_prefix}/items")
app.include_router(locations_router, prefix=f"{api_prefix}/locations")
app.include_router(reminders_router, prefix=f"{api_prefix}/reminders")
app.include_router(recipes_router, prefix=f"{api_prefix}/recipes")
app.include_router(agent_router, prefix=f"{api_prefix}/agent")


def flash(request: Request, message: str, category: str = "success"):
    request.session.setdefault("flashes", []).append({"message": message, "category": category})


def get_flashes(request: Request):
    flashes = request.session.pop("flashes", [])
    return flashes[0] if flashes else None


@app.get("/health")
def health_check():
    return {"status": "ok", "service": settings.app_name}


# ============ WEB UI ROUTES ============

@app.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    return RedirectResponse(url="/dashboard", status_code=HTTP_303_SEE_OTHER)


# Dashboard UI
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, session: Session = Depends(get_session)):
    from datetime import date as _date

    today = _date.today()
    items = session.exec(select(Item)).all()
    locations = session.exec(select(Location).order_by(Location.name)).all()
    total_items = len(items)
    expiring_cutoff = today + timedelta(days=7)

    expired = [i for i in items if i.expiry_date and i.expiry_date < today]
    expiring = [i for i in items if i.expiry_date and today <= i.expiry_date <= expiring_cutoff]
    fresh = [i for i in items if not i.expiry_date or i.expiry_date > expiring_cutoff]

    by_location = {}
    for loc in locations:
        by_location[loc.name] = sum(1 for i in items if i.location_id == loc.id)
    by_location["Uncategorized"] = sum(1 for i in items if i.location_id is None)

    recently_added = sorted(items, key=lambda i: i.created_at, reverse=True)[:5]
    needs_attention = sorted(expired + expiring, key=lambda i: i.expiry_date or today)[:6]

    return render_template("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "total_items": total_items,
        "expired": expired,
        "expiring": expiring,
        "fresh": fresh,
        "by_location": by_location,
        "locations_count": len(locations),
        "recently_added": recently_added,
        "needs_attention": needs_attention,
        "today": today,
        "expiring_cutoff": expiring_cutoff,
    })


# Items UI
@app.get("/items", response_class=HTMLResponse)
def items_page(
    request: Request,
    session: Session = Depends(get_session),
    search: Optional[str] = None,
    location_id: Optional[str] = None,
    filter: str = "all",
    sort: str = "name_asc",
):
    from app.api.routes import list_items
    location_id_int = int(location_id) if location_id and location_id.strip().isdigit() else None
    items = list_items(session, location_id_int, filter == "expiring", 7, search, sort=sort)
    locations = session.exec(select(Location).order_by(Location.name)).all()
    today = date.today()
    expiring_cutoff = today + timedelta(days=7)
    return render_template("items.html", {
        "request": request,
        "items": items,
        "locations": locations,
        "search": search,
        "location_id": location_id,
        "filter": filter,
        "sort": sort,
        "today": today,
        "expiring_cutoff": expiring_cutoff,
        "flash": get_flashes(request),
        "active_page": "items",
    })


@app.get("/items/new", response_class=HTMLResponse)
def new_item_page(request: Request, session: Session = Depends(get_session)):
    locations = session.exec(select(Location).order_by(Location.name)).all()
    return render_template("item_form.html", {
        "request": request,
        "locations": locations,
        "categories": ITEM_CATEGORIES,
        "item": None,
    })


@app.post("/items/new")
def create_item_web(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    location_id: Optional[int] = Form(None),
    category: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
):
    from app.api.routes import create_item
    from app.models.schemas import ItemCreate
    item = ItemCreate(name=name, quantity=quantity, unit=unit, location_id=location_id, category=category, expiry_date=expiry_date, barcode=barcode)
    create_item(item, session)
    flash(request, "Item created")
    return RedirectResponse(url="/items", status_code=HTTP_303_SEE_OTHER)


@app.get("/items/{item_id}/edit", response_class=HTMLResponse)
def edit_item_page(item_id: int, request: Request, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    locations = session.exec(select(Location).order_by(Location.name)).all()
    return render_template("item_form.html", {
        "request": request,
        "item": item,
        "locations": locations,
        "categories": ITEM_CATEGORIES,
    })


@app.post("/items/{item_id}/edit")
def update_item_web(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(...),
    location_id: Optional[int] = Form(None),
    category: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
):
    from app.api.routes import update_item
    from app.models.schemas import ItemUpdate
    item = ItemUpdate(name=name, quantity=quantity, unit=unit, location_id=location_id, category=category, expiry_date=expiry_date, barcode=barcode)
    update_item(item_id, item, session)
    flash(request, "Item updated")
    return RedirectResponse(url="/items", status_code=HTTP_303_SEE_OTHER)


# Locations UI
@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request, session: Session = Depends(get_session)):
    from app.api.routes import list_locations
    locations = list_locations(session)
    return render_template("locations.html", {
        "request": request,
        "locations": locations,
        "flash": get_flashes(request),
        "active_page": "locations",
    })


@app.get("/locations/new", response_class=HTMLResponse)
def new_location_page(request: Request):
    return render_template("location_form.html", {
        "request": request,
        "location": None,
    })


@app.post("/locations/new")
def create_location_web(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    description: Optional[str] = Form(None),
):
    from app.api.routes import create_location
    from app.models.schemas import LocationCreate
    loc = LocationCreate(name=name, description=description)
    create_location(loc, session)
    flash(request, "Location created")
    return RedirectResponse(url="/locations", status_code=HTTP_303_SEE_OTHER)


@app.get("/locations/{loc_id}/edit", response_class=HTMLResponse)
def edit_location_page(loc_id: int, request: Request, session: Session = Depends(get_session)):
    loc = session.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    return render_template("location_form.html", {
        "request": request,
        "location": loc,
    })


@app.post("/locations/{loc_id}/edit")
def update_location_web(
    loc_id: int,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    description: Optional[str] = Form(None),
):
    from app.api.routes import update_location
    from app.models.schemas import LocationUpdate
    loc = LocationUpdate(name=name, description=description)
    update_location(loc_id, loc, session)
    flash(request, "Location updated")
    return RedirectResponse(url="/locations", status_code=HTTP_303_SEE_OTHER)


# Reminders UI
@app.get("/reminders", response_class=HTMLResponse)
def reminders_page(request: Request, session: Session = Depends(get_session)):
    from app.api.routes import get_expiring, get_expired
    expiring = get_expiring(session, 7)
    expired = get_expired(session)
    return render_template("reminders.html", {
        "request": request,
        "expiring": expiring,
        "expired": expired,
        "flash": get_flashes(request),
        "active_page": "reminders",
    })


# Recipes UI
@app.get("/recipes", response_class=HTMLResponse)
def recipes_page(request: Request):
    return render_template("recipes.html", {
        "request": request,
        "flash": get_flashes(request),
        "active_page": "recipes",
        "meal_types": MEAL_TYPES,
    })


@app.get("/recipes/partial", response_class=HTMLResponse)
def recipes_partial(
    request: Request,
    session: Session = Depends(get_session),
    meal_type: Optional[str] = None,
):
    query = select(RecipeSuggestion)
    if meal_type:
        query = query.where(RecipeSuggestion.meal_type == meal_type)
    recipes = session.exec(query.order_by(RecipeSuggestion.created_at.desc()).limit(5)).all()
    return render_template("partials/recipes_list.html", {
        "request": request,
        "recipes": recipes,
        "meal_types": MEAL_TYPES,
        "active_meal": meal_type,
    })


@app.get("/")
def root():
    return {"message": "Pantry Assist API", "docs": "/docs"}