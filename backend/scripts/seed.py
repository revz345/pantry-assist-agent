#!/usr/bin/env python
"""Seed database with dummy data for testing - Indian/Idli-Dosa focused.

WARNING: This DELETES all existing items and locations first. Run with:
    python scripts/seed.py           # prompts for confirmation if DB is non-empty
    python scripts/seed.py --force   # skips the prompt (scripts/CI)
"""

import sys
from datetime import date, timedelta
from sqlmodel import Session, select

from app.db.session import engine, init_db
from app.models.schemas import Item, Location


def _confirm_or_abort(session) -> None:
    """Refuse to wipe a non-empty database without explicit confirmation."""
    existing_items = len(session.exec(select(Item)).all())
    existing_locs = len(session.exec(select(Location)).all())
    if existing_items == 0 and existing_locs == 0:
        return  # empty DB — nothing to lose
    if "--force" in sys.argv:
        print(f"[seed] --force: deleting {existing_items} items, {existing_locs} locations")
        return
    print(
        f"[seed] WARNING: this will DELETE {existing_items} items and "
        f"{existing_locs} locations from the database."
    )
    answer = input("[seed] Type 'yes' to continue: ").strip().lower()
    if answer != "yes":
        print("[seed] Aborted — no changes made.")
        sys.exit(1)


def seed():
    init_db()

    with Session(engine) as session:
        _confirm_or_abort(session)

        # Clear existing
        for item in session.exec(select(Item)).all():
            session.delete(item)
        for loc in session.exec(select(Location)).all():
            session.delete(loc)
        session.commit()

        # Locations
        fridge = Location(name="Fridge", description="Main refrigerator")
        freezer = Location(name="Freezer", description="Deep freezer")
        pantry = Location(name="Pantry", description="Dry storage shelves")
        spice_rack = Location(name="Spice Rack", description="Wall-mounted spices")
        idli_dosa = Location(name="Idli-Dosa Kit", description="Batters & fermentation")
        
        for loc in [fridge, freezer, pantry, spice_rack, idli_dosa]:
            session.add(loc)
        session.commit()
        for loc in [fridge, freezer, pantry, spice_rack, idli_dosa]:
            session.refresh(loc)

        today = date.today()
        
        items = [
            # ===== IDLI-DOSA ESSENTIALS =====
            # Batters (fermenting/ready)
            Item(name="Idli Batter (fermented)", quantity=2, unit="l", category="Batters & Fermentation", location_id=idli_dosa.id, expiry_date=today + timedelta(days=3)),
            Item(name="Dosa Batter (fermented)", quantity=1.5, unit="l", category="Batters & Fermentation", location_id=idli_dosa.id, expiry_date=today + timedelta(days=2)),
            Item(name="Idli Rice (parboiled)", quantity=5, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Urad Dal (whole, skinless)", quantity=2, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Fenugreek Seeds (methi)", quantity=100, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Poha (flattened rice)", quantity=500, unit="g", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=180)),
            
            # Chutneys & sides
            Item(name="Coconut Chutney (fresh)", quantity=300, unit="g", category="Chutneys & Pickles", location_id=fridge.id, expiry_date=today + timedelta(days=2)),
            Item(name="Tomato Chutney", quantity=200, unit="g", category="Chutneys & Pickles", location_id=fridge.id, expiry_date=today + timedelta(days=4)),
            Item(name="Sambar Powder", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=180)),
            Item(name="Gunpowder (Milagai Podi)", quantity=150, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=180)),
            
            # Fridge - Indian staples
            Item(name="Curd/Yogurt", quantity=500, unit="g", category="Dairy", location_id=fridge.id, expiry_date=today + timedelta(days=5)),
            Item(name="Milk (full cream)", quantity=1, unit="l", category="Dairy", location_id=fridge.id, expiry_date=today + timedelta(days=3)),
            Item(name="Butter (Amul)", quantity=200, unit="g", category="Dairy", location_id=fridge.id, expiry_date=today + timedelta(days=20)),
            Item(name="Ghee", quantity=500, unit="g", category="Dairy", location_id=fridge.id, expiry_date=today + timedelta(days=365)),
            Item(name="Coriander Leaves", quantity=2, unit="pcs", category="Leafy Greens", location_id=fridge.id, expiry_date=today + timedelta(days=3)),
            Item(name="Curry Leaves", quantity=1, unit="pcs", category="Leafy Greens", location_id=fridge.id, expiry_date=today + timedelta(days=7)),
            Item(name="Green Chilies", quantity=100, unit="g", category="Vegetables", location_id=fridge.id, expiry_date=today + timedelta(days=7)),
            Item(name="Ginger", quantity=100, unit="g", category="Vegetables", location_id=fridge.id, expiry_date=today + timedelta(days=14)),
            Item(name="Garlic", quantity=200, unit="g", category="Vegetables", location_id=fridge.id, expiry_date=today + timedelta(days=30)),
            Item(name="Carrots", quantity=500, unit="g", category="Vegetables", location_id=fridge.id, expiry_date=today + timedelta(days=10)),
            Item(name="Beans (French)", quantity=300, unit="g", category="Vegetables", location_id=fridge.id, expiry_date=today + timedelta(days=7)),
            
            # Freezer
            Item(name="Frozen Grated Coconut", quantity=2, unit="pcs", category="Frozen", location_id=freezer.id, expiry_date=today + timedelta(days=180)),
            Item(name="Frozen Peas", quantity=500, unit="g", category="Frozen", location_id=freezer.id, expiry_date=today + timedelta(days=180)),
            Item(name="Idli Batter (backup frozen)", quantity=1, unit="l", category="Batters & Fermentation", location_id=freezer.id, expiry_date=today + timedelta(days=60)),
            
            # Pantry - Grains & Dals
            Item(name="Toor Dal (pigeon pea)", quantity=2, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Moong Dal (yellow)", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Chana Dal", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Rajma (kidney beans)", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Chickpeas (kabuli chana)", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Basmati Rice", quantity=5, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Sona Masoori Rice", quantity=5, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Wheat Flour (atta)", quantity=5, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=180)),
            Item(name="Rava (Semolina/Sooji)", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=180)),
            Item(name="Besan (Gram Flour)", quantity=500, unit="g", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=180)),
            Item(name="Rice Flour", quantity=1, unit="kg", category="Grains & Dals", location_id=pantry.id, expiry_date=today + timedelta(days=180)),
            
            # Spices
            Item(name="Turmeric Powder", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Red Chili Powder", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Coriander Powder", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Cumin Seeds (Jeera)", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Mustard Seeds (Rai)", quantity=200, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Asafoetida (Hing)", quantity=50, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Garam Masala", quantity=100, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Kashmiri Chili Powder", quantity=100, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Black Pepper", quantity=100, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Cardamom (Green)", quantity=50, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Cloves", quantity=50, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Cinnamon Stick", quantity=50, unit="g", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            Item(name="Bay Leaves", quantity=20, unit="pcs", category="Spices", location_id=spice_rack.id, expiry_date=today + timedelta(days=365)),
            
            # Oils
            Item(name="Sesame Oil (Gingelly)", quantity=1, unit="l", category="Oils & Ghee", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Coconut Oil", quantity=500, unit="ml", category="Oils & Ghee", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            Item(name="Sunflower Oil", quantity=1, unit="l", category="Oils & Ghee", location_id=pantry.id, expiry_date=today + timedelta(days=365)),
            
            # Expired (for testing reminders)
            Item(name="Old Coconut Chutney", quantity=100, unit="g", category="Chutneys & Pickles", location_id=fridge.id, expiry_date=today - timedelta(days=3)),
            Item(name="Spoiled Sambar", quantity=200, unit="g", category="Condiments", location_id=fridge.id, expiry_date=today - timedelta(days=1)),
        ]

        for item in items:
            session.add(item)
        session.commit()
        
        print(f"Seeded: {len(items)} items across 5 locations")
        print(f"  Idli-Dosa Kit: 6 items (batters, rice, dal, methi, poha)")
        print(f"  Fridge: 13 items (chutneys, veggies, dairy, greens)")
        print(f"  Freezer: 3 items")
        print(f"  Pantry: 14 items (grains, dals, oils)")
        print(f"  Spice Rack: 16 items (all masalas)")
        print(f"  Expired: 2 items (for reminder testing)")

if __name__ == "__main__":
    seed()