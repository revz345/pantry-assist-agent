import asyncio

import pytest
from fastapi.testclient import TestClient

from app.services import barcode as barcode_service


# ─── Barcode lookup (unit) ──────────────────────────────────────
def test_lookup_rejects_non_numeric():
    assert asyncio.run(barcode_service.lookup_barcode("abc")) is None
    assert asyncio.run(barcode_service.lookup_barcode("")) is None


@pytest.mark.parametrize("barcode", ["0000000000000", "1111111111111", "9999999999999"])
def test_lookup_unknown_returns_none(barcode, monkeypatch):
    class _Resp:
        status_code = 404

        def json(self):
            return {"status": 0}

    async def fake_get(url, timeout=None):
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    assert asyncio.run(barcode_service.lookup_barcode(barcode)) is None


def test_lookup_known_real_product():
    result = asyncio.run(barcode_service.lookup_barcode("5449000000996"))
    if result is not None:  # network may be unavailable in CI
        assert result["name"]  # coca-cola
        assert result["category"]


# ─── Scan endpoint (integration) ────────────────────────────────
def test_scan_unknown_falls_back_to_placeholder(client: TestClient, monkeypatch):
    async def fake_lookup(barcode):
        return None

    monkeypatch.setattr(barcode_service, "lookup_barcode", fake_lookup)
    resp = client.post("/api/v1/items/scan?barcode=1234567890123")
    assert resp.status_code == 200
    assert resp.json()["barcode"] == "1234567890123"
    assert "Scanned item" in resp.json()["name"]


def test_scan_known_uses_product_name(client: TestClient, monkeypatch):
    async def fake_lookup(barcode):
        return {"name": "Coca-Cola", "category": "Colas", "quantity": "33 cl", "brand": "Coca-Cola"}

    monkeypatch.setattr(barcode_service, "lookup_barcode", fake_lookup)
    resp = client.post("/api/v1/items/scan?barcode=5449000000996")
    assert resp.status_code == 200
    item = resp.json()
    assert item["barcode"] == "5449000000996"
    assert item["name"] == "Coca-Cola"
    assert item["category"] == "Colas"

    # Second scan returns existing (no lookup)
    resp2 = client.post("/api/v1/items/scan?barcode=5449000000996")
    assert resp2.json()["id"] == item["id"]
