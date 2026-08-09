from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.schemas import (
    Item,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    Location,
    LocationCreate,
    LocationRead,
    LocationUpdate,
    RecipeFeedback,
    RecipeFeedbackCreate,
    RecipeFeedbackRead,
    RecipeSuggestion,
    RecipeSuggestionRead,
)

router = APIRouter(tags=["items"])


@router.get("", response_model=list[ItemRead])
def list_items(
    session: Session = Depends(get_session),
    location_id: int | None = None,
    expiring_soon: bool = False,
    days: int = 7,
    search: str | None = None,
    sort: str = "created_desc",
    skip: int = 0,
    limit: int = 100,
):
    query = select(Item)
    if location_id:
        query = query.where(Item.location_id == location_id)
    if expiring_soon:
        cutoff = date.today() + timedelta(days=days)
        query = query.where(Item.expiry_date.is_not(None)).where(Item.expiry_date <= cutoff)
    if search:
        query = query.where(Item.name.ilike(f"%{search}%"))
    sort_map = {
        "name_asc": (Item.name, "asc"),
        "name_desc": (Item.name, "desc"),
        "expiry_asc": (Item.expiry_date, "asc"),
        "expiry_desc": (Item.expiry_date, "desc"),
        "quantity_asc": (Item.quantity, "asc"),
        "quantity_desc": (Item.quantity, "desc"),
        "created_asc": (Item.created_at, "asc"),
        "created_desc": (Item.created_at, "desc"),
    }
    column, direction = sort_map.get(sort, sort_map["created_desc"])
    order = column.asc() if direction == "asc" else column.desc()
    query = query.offset(skip).limit(limit).order_by(order)
    return session.exec(query).all()


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(item: ItemCreate, session: Session = Depends(get_session)):
    db_item = Item.model_validate(item)
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(item_id: int, item_update: ItemUpdate, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    update_data = item_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    session.delete(item)
    session.commit()


class BulkDeleteRequest(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
def bulk_delete_items(body: BulkDeleteRequest, session: Session = Depends(get_session)):
    """Delete multiple items by id."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No item ids provided")
    deleted = 0
    for item_id in body.ids:
        item = session.get(Item, item_id)
        if item:
            session.delete(item)
            deleted += 1
    session.commit()
    return {"deleted": deleted}


@router.post("/scan", response_model=ItemRead)
async def scan_item(barcode: str = Query(...), session: Session = Depends(get_session)):
    """Lookup or create item by barcode.

    Checks the DB first, then falls back to a real product lookup via the
    Open Food Facts API. If the barcode is unknown there too, creates a
    generic "Scanned item" placeholder.
    """
    existing = session.exec(select(Item).where(Item.barcode == barcode)).first()
    if existing:
        return existing

    from app.services.barcode import lookup_barcode

    product = await lookup_barcode(barcode)
    if product:
        new_item = Item(
            name=product["name"],
            barcode=barcode,
            quantity=1,
            category=product.get("category"),
        )
    else:
        new_item = Item(name=f"Scanned item {barcode}", barcode=barcode, quantity=1)
    session.add(new_item)
    session.commit()
    session.refresh(new_item)
    return new_item


# Locations router
locations_router = APIRouter(tags=["locations"])


@locations_router.get("", response_model=list[LocationRead])
def list_locations(session: Session = Depends(get_session), skip: int = 0, limit: int = 100):
    return session.exec(select(Location).offset(skip).limit(limit).order_by(Location.name)).all()


@locations_router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(loc: LocationCreate, session: Session = Depends(get_session)):
    db_loc = Location.model_validate(loc)
    session.add(db_loc)
    session.commit()
    session.refresh(db_loc)
    return db_loc


@locations_router.get("/{loc_id}", response_model=LocationRead)
def get_location(loc_id: int, session: Session = Depends(get_session)):
    loc = session.get(Location, loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


@locations_router.patch("/{loc_id}", response_model=LocationRead)
def update_location(loc_id: int, loc_update: LocationUpdate, session: Session = Depends(get_session)):
    loc = session.get(Location, loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    update_data = loc_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(loc, field, value)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


@locations_router.delete("/{loc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(loc_id: int, session: Session = Depends(get_session)):
    loc = session.get(Location, loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    session.delete(loc)
    session.commit()


# Reminders router
reminders_router = APIRouter(tags=["reminders"])


@reminders_router.get("/expiring", response_model=list[ItemRead])
def get_expiring(
    session: Session = Depends(get_session),
    days: int = Query(7, ge=1, le=365),
):
    cutoff = date.today() + timedelta(days=days)
    items = session.exec(
        select(Item)
        .where(Item.expiry_date.is_not(None))
        .where(Item.expiry_date <= cutoff)
        .order_by(Item.expiry_date)
    ).all()
    return items


@reminders_router.get("/expired", response_model=list[ItemRead])
def get_expired(session: Session = Depends(get_session)):
    items = session.exec(
        select(Item)
        .where(Item.expiry_date.is_not(None))
        .where(Item.expiry_date < date.today())
        .order_by(Item.expiry_date)
    ).all()
    return items


# Recipes router
recipes_router = APIRouter(tags=["recipes"])


@recipes_router.get("/suggestions", response_model=list[RecipeSuggestionRead])
def get_recipe_suggestions(
    session: Session = Depends(get_session),
    limit: int = Query(5, ge=1, le=20),
    meal_type: str | None = None,
):
    """LLM-generated recipes from current inventory (agent populates this)."""
    query = select(RecipeSuggestion)
    if meal_type:
        query = query.where(RecipeSuggestion.meal_type == meal_type)
    return session.exec(query.order_by(RecipeSuggestion.created_at.desc()).limit(limit)).all()


@recipes_router.post("/feedback", response_model=RecipeFeedbackRead, status_code=status.HTTP_201_CREATED)
def submit_recipe_feedback(feedback: RecipeFeedbackCreate, session: Session = Depends(get_session)):
    """User rates/accepts a recipe suggestion."""
    db_feedback = RecipeFeedback.model_validate(feedback)
    session.add(db_feedback)
    session.commit()
    session.refresh(db_feedback)
    return db_feedback
