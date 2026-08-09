from datetime import datetime

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.schemas import Item, RecipeSuggestion

settings = get_settings()


async def generate_recipe_suggestions(session: Session) -> list[RecipeSuggestion]:
    """Generate recipe suggestions using LLM based on current inventory."""
    if not settings.openai_api_key:
        return []

    # Get non-expired items with quantity > 0
    items = session.exec(
        select(Item)
        .where(Item.quantity > 0)
        .where((Item.expiry_date.is_(None)) | (Item.expiry_date >= datetime.utcnow().date()))
    ).all()

    if not items:
        return []

    inventory_summary = "\n".join([
        f"- {item.name}: {item.quantity} {item.unit.value}" + (f" [{item.category}]" if item.category else "") + (f" (expires {item.expiry_date})" if item.expiry_date else "")
        for item in items
    ])

    prompt = f"""You are a helpful cooking assistant for a South Indian / Indian household. Given the following inventory, suggest 4-6 recipes that use these ingredients.
Prioritize recipes that use items expiring soon. Balance the suggestions across meal times: at least one breakfast, one lunch, one snack, and one dinner.

For each recipe include:
- title (string)
- description (string, optional)
- meal_type (string): one of "breakfast", "lunch", "snack", or "dinner"
- ingredients (array of strings)
- instructions (array of strings)
- estimated_time_minutes (integer, optional)
- servings (integer, optional)

Inventory (with category in [brackets]):
{inventory_summary}

Return ONLY valid JSON array."""

    try:
        from openai import AsyncOpenAI
        import json
        import re
        client = AsyncOpenAI(
            api_key=settings.openai_api_key or "dummy",
            base_url=settings.openai_base_url,
        )
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )
        content = response.choices[0].message.content
        # Extract JSON from markdown code blocks if present
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        recipes_data = json.loads(content)

        from app.models.schemas import MealType
        valid_meals = {m.value for m in MealType}
        suggestions = []
        for r in recipes_data:
            meal_raw = str(r.get("meal_type", "")).strip().lower()
            meal_type = meal_raw if meal_raw in valid_meals else None
            suggestion = RecipeSuggestion(
                title=r["title"],
                description=r.get("description"),
                meal_type=meal_type,
                ingredients=r["ingredients"],
                instructions=r["instructions"],
                estimated_time_minutes=r.get("estimated_time_minutes"),
                servings=r.get("servings"),
                source_inventory_snapshot=inventory_summary,
            )
            session.add(suggestion)
            suggestions.append(suggestion)

        session.commit()
        for s in suggestions:
            session.refresh(s)
        return suggestions
    except Exception as e:
        print(f"[Agent] Error generating recipes: {e}")
        import traceback
        traceback.print_exc()
        return []


async def check_expiry_alerts(session: Session) -> list[Item]:
    """Check for items expiring soon or already expired."""
    from datetime import date, timedelta
    today = date.today()
    soon = today + timedelta(days=3)

    expiring = session.exec(
        select(Item)
        .where(Item.expiry_date.is_not(None))
        .where(Item.expiry_date <= soon)
        .where(Item.expiry_date >= today)
    ).all()

    expired = session.exec(
        select(Item)
        .where(Item.expiry_date.is_not(None))
        .where(Item.expiry_date < today)
    ).all()

    return {"expiring_soon": expiring, "expired": expired}


async def run_agent_cycle(session: Session) -> dict:
    """Main agent cycle - runs periodically."""
    results = {}

    # Generate recipe suggestions
    recipes = await generate_recipe_suggestions(session)
    results["recipes_generated"] = len(recipes)

    # Check expiry alerts
    alerts = await check_expiry_alerts(session)
    results["expiring_soon_count"] = len(alerts["expiring_soon"])
    results["expired_count"] = len(alerts["expired"])

    return results
