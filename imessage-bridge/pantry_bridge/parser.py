"""Natural-language parsing for the bridge: quantities, units, categories,
locations, expiry dates, and the main `add` command parser."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# ─── Unit / Quantity Parsing ────────────────────────────────────
UNIT_ALIASES = {
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg",
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    "l": "l", "lt": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "ml": "ml", "mls": "ml", "millilitre": "ml", "milliliter": "ml",
    "pcs": "pcs", "pc": "pcs", "piece": "pcs", "pieces": "pcs",
    "bunch": "pcs", "bunches": "pcs", "bag": "pcs", "bags": "pcs",
    "pack": "pcs", "packet": "pcs", "packets": "pcs", "box": "pcs", "boxes": "pcs",
    "bottle": "pcs", "bottles": "pcs", "jar": "pcs", "jars": "pcs",
    "can": "pcs", "cans": "pcs", "carton": "pcs", "dozen": "pcs", "dozens": "pcs",
    "head": "pcs", "heads": "pcs", "bundle": "pcs", "sprig": "pcs", "sprigs": "pcs",
    "cup": "cup", "cups": "cup",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsps": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp",
}

# Sort aliases longest-first so "tablespoons" matches before "tbsp"-like prefixes
_UNIT_ALTERNATIVES = sorted(UNIT_ALIASES.keys(), key=len, reverse=True)
_UNIT_PATTERN = r"(?:\d+\.?\d*)\s*(" + "|".join(_UNIT_ALTERNATIVES) + r")s?"

FILLER_WORDS = {"of", "a", "an", "the", "please", "pls", "some", "and", "to", "into", "in", "my", "for", "with", "bunch", "it", "this", "that", "they"}

# ─── Category Inference ─────────────────────────────────────────
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Frozen", ["frozen", "ice cream", "icecream"]),
    ("Oils & Ghee", [
        "sesame oil", "gingelly", "coconut oil", "sunflower oil", "mustard oil",
        "olive oil", "ghee", "oil",
    ]),
    ("Leafy Greens", [
        "spinach", "palak", "coriander", "dhania", "cilantro", "mint", "pudina",
        "methi", "fenugreek leaves", "curry leaves", "kadi patta", "lettuce",
        "kale", "amaranth", "sarso", "bathua", "spring onion", "leafy",
        "cabbage", "spinach", "mustard greens",
    ]),
    ("Vegetables", [
        "onion", "potato", "tomato", "carrot", "beans", "brinjal", "eggplant",
        "cauliflower", "gobi", "capsicum", "bell pepper", "cucumber", "pumpkin",
        "bottle gourd", "lauki", "ridge gourd", "turai", "bitter gourd",
        "karela", "okra", "bhindi", "peas", "radish", "mooli", "beetroot",
        "corn", "maize", "broccoli", "zucchini", "ginger", "garlic",
        "green chilli", "green chili", "chilli", "chili", "lemon", "yam",
        "arbi", "sweet potato", "veggie", "vegetable", "parwal", "drumstick",
        "tinda", "ash gourd", "lauki", "green beans", "snake gourd",
    ]),
    ("Fruits", [
        "apple", "banana", "mango", "orange", "grapes", "papaya", "pomegranate",
        "guava", "pineapple", "watermelon", "muskmelon", "coconut", "lime",
        "kiwi", "peach", "plum", "strawberry", "blueberry", "fruit",
    ]),
    ("Dairy", [
        "milk", "curd", "yogurt", "yoghurt", "buttermilk", "paneer", "cheese",
        "butter", "ghee", "cream", "khoya", "mawa", "lassi", "dahi", "egg", "eggs",
    ]),
    ("Chutneys & Pickles", [
        "chutney", "pickle", "achar", "jam", "sauce", "ketchup", "murabba", "podi",
    ]),
    ("Batters & Fermentation", [
        "batter", "idli", "dosa", "appam", "uttapam", "fermentation", "yeast",
    ]),
    ("Grains & Dals", [
        "rice", "basmati", "sona masoori", "idli rice", "dal", "toor", "arhar",
        "moong", "urad", "chana", "rajma", "chickpea", "kabuli", "atta", "wheat",
        "maida", "rava", "sooji", "semolina", "poha", "besan", "gram flour",
        "rice flour", "oats", "barley", "quinoa", "millet", "ragi", "jowar",
        "bajra", "flour", "pulses", "lentils", "masoor", "kala chana",
    ]),
    ("Spices", [
        "turmeric", "haldi", "chilli powder", "chili powder", "coriander powder",
        "dhania powder", "cumin", "jeera", "mustard", "rai", "hing",
        "asafoetida", "garam masala", "kashmiri", "black pepper", "pepper",
        "cardamom", "elaichi", "clove", "laung", "cinnamon", "dalchini",
        "bay leaf", "tej patta", "sambar powder", "gunpowder", "fennel",
        "saunf", "curry powder", "mango powder", "amchur", "sesame seed", "til",
        "poppy", "spice", "masala",
    ]),
    ("Condiments", [
        "vinegar", "salt", "sugar", "jaggery", "gud", "honey", "soy sauce",
        "sambar", "coconut chutney", "tomato chutney", "spread", "mayonnaise",
    ]),
]


def infer_category(name: str) -> str | None:
    """Best-effort category for an item name, or None if unknown."""
    n = name.lower()
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            # Word-boundary match (plural-tolerant) so "hing" doesn't match "thing"
            if re.search(r"\b" + re.escape(kw) + r"s?\b", n):
                return category
    return None


# Smart location when user doesn't say one (location_id).
CATEGORY_DEFAULT_LOCATION = {
    "Frozen": 2,                      # Freezer
    "Leafy Greens": 1,                # Fridge
    "Vegetables": 1,                  # Fridge
    "Fruits": 1,                      # Fridge
    "Dairy": 1,                       # Fridge
    "Chutneys & Pickles": 1,          # Fridge
    "Batters & Fermentation": 5,      # Idli-Dosa Kit
    "Spices": 4,                      # Spice Rack
    "Grains & Dals": 3,               # Pantry
    "Oils & Ghee": 3,                 # Pantry
    "Condiments": 3,                  # Pantry
}


def normalize_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", phone or "")


def _extract_location_id(text: str) -> int | None:
    """Map a location word to its id, or None if not a location mention."""
    t = text.lower()
    if "freezer" in t:
        return 2
    if "fridge" in t or "refrigerator" in t:
        return 1
    if "pantry" in t:
        return 3
    if "spice" in t:
        return 4
    if "idli" in t or "dosa" in t:
        return 5
    return None


# ─── Natural-Language Add Parsing ──────────────────────────────
@dataclass
class ParsedItem:
    name: str
    quantity: float
    unit: str
    category: str | None
    location_id: int | None
    expiry_date: str | None
    error: str | None = None


def parse_add_command(text: str) -> ParsedItem:
    """Parse 'add spinach of 1 bunch' → name='Spinach', qty=1, unit='pcs'.
    Also handles 'to the fridge', 'expires friday', weights/volumes, etc."""
    t = text.strip().lower()
    # Strip leading command words (also bare "add"/"buy" so we can error on them)
    for cmd in ("please add", "pls add", "i bought ", "add", "buy", "get"):
        if t == cmd or t.startswith(cmd + " "):
            t = t[len(cmd):].strip()
            break

    # --- Expiry ---
    # Handles: "expires friday", "expire this wednesday", "expires by wednesday",
    # "expires on monday", "expires tomorrow", "expires in 3 days", "expires in
    # 2 weeks", "expires in a week", "expires next friday".
    expiry = None
    today = datetime.now()
    weekday_map = {
        "today": 0, "tomorrow": 1,
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,  # datetime.weekday() (Mon=0)
    }
    exp_match = re.search(
        r"expires?\s+(?:(?:by|on|in|this|next|the|coming|of|a|an)\s+)*"
        r"((?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"|weeks?|months?|\d+)"
        r"\s*(days?|weeks?|months?)?",
        t,
    )
    if exp_match:
        token, unit = exp_match.group(1).lower(), exp_match.group(2)
        matched_text = exp_match.group(0)
        target = None
        if token == "today":
            target = today
        elif token == "tomorrow":
            target = today + timedelta(days=1)
        elif token in ("week", "weeks"):
            target = today + timedelta(days=7)
        elif token in ("month", "months"):
            target = today + timedelta(days=30)
        elif token in weekday_map:
            target_wd = weekday_map[token]
            days_ahead = (target_wd - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # same weekday mentioned = next week
            if "next " in matched_text:
                days_ahead += 7
            target = today + timedelta(days=days_ahead)
        elif token.isdigit():
            amount = int(token)
            if unit and unit.startswith("month"):
                target = today + timedelta(days=amount * 30)
            elif unit and unit.startswith("week"):
                target = today + timedelta(days=amount * 7)
            else:
                target = today + timedelta(days=amount)
        if target:
            expiry = target.strftime("%Y-%m-%d")
        t = exp_match.string[: exp_match.start()] + " " + exp_match.string[exp_match.end():]

    # --- Explicit location ---
    # Only match prepositional phrases ("to the fridge", "in freezer") or exact
    # location names — NOT words that are also item names ("dosa batter").
    location_id = None
    for loc, lid in [
        ("freezer", 2), ("fridge", 1), ("refrigerator", 1), ("pantry", 3),
        ("spice rack", 4), ("idli-dosa kit", 5),
    ]:
        m = re.search(rf"(?:\b(?:in|into|to|the|on)\s+)?{re.escape(loc)}\b", t)
        if m:
            location_id = lid
            t = t[: m.start()] + " " + t[m.end():]
            break

    # --- Quantity + unit ---
    qty_match = re.search(_UNIT_PATTERN, t, re.IGNORECASE)
    if qty_match:
        raw_unit = qty_match.group(1).lower().rstrip("s")
        quantity = float(re.search(r"\d+\.?\d*", qty_match.group(0)).group(0))
        unit = UNIT_ALIASES.get(raw_unit, UNIT_ALIASES.get(raw_unit + "s", "pcs"))
        t = t.replace(qty_match.group(0), " ", 1)
    else:
        # bare "2" with no unit
        bare_qty = re.search(r"\b(\d+\.?\d*)\b", t)
        if bare_qty:
            quantity = float(bare_qty.group(1))
            unit = "pcs"
            t = t.replace(bare_qty.group(0), " ", 1)
        else:
            quantity = 1
            unit = "pcs"

    # --- Clean name: strip filler words + leftovers ---
    for word in FILLER_WORDS:
        t = re.sub(r"\b" + word + r"\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–,.:")
    t = re.sub(r"[.,;:!?]+$", "", t)

    name = t.strip()
    if not name or len(name) > 100:
        return ParsedItem("", 1, "pcs", None, None, None,
                          error=f"Could not parse item name from: '{text}'")

    category = infer_category(name)

    # Location fallback by category
    if location_id is None and category:
        location_id = CATEGORY_DEFAULT_LOCATION.get(category)

    # Title-case nicely (capitalize each word)
    name = name.title()

    return ParsedItem(name, quantity, unit, category, location_id, expiry)
