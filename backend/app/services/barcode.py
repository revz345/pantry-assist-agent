"""Barcode product lookup via the Open Food Facts public API."""

import httpx

OPENFOODFACTS_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"


async def lookup_barcode(barcode: str) -> dict | None:
    """Look up a barcode on Open Food Facts.

    Returns a dict with the product's name, category, and quantity if found,
    or None if the barcode is unknown / the lookup fails (so callers can fall
    back to a generic item).
    """
    if not barcode or not barcode.isdigit():
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(OPENFOODFACTS_URL.format(barcode=barcode))
        if r.status_code != 200:
            return None
        data = r.json()
        if not data.get("status") or data.get("status") != 1:
            return None
        product = data.get("product") or {}
        name = (product.get("product_name")
                or product.get("generic_name")
                or product.get("brands"))
        if not name:
            return None
        return {
            "name": str(name).strip()[:100],
            "category": (product.get("categories") or "").split(",")[0].strip()[:60] or None,
            "quantity": product.get("quantity") or None,
            "brand": (product.get("brands") or "").strip() or None,
        }
    except Exception:
        return None
