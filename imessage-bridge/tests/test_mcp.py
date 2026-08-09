"""Tests for the pantry MCP server's barcode scanning integration."""
import json

import pantry_mcp


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


def test_scan_barcode_success(monkeypatch):
    captured = {}

    async def fake_get(self, url, timeout=None):
        if url.endswith("/locations"):
            return _Resp(200, [{"id": 1, "name": "Fridge"}, {"id": 2, "name": "Freezer"}])
        return _Resp(200, {"id": 58, "name": "coca-cola", "quantity": 1.0,
                           "unit": "pcs", "category": "Colas", "location_id": None})

    async def fake_post(self, url, params=None, json=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, {"id": 58, "name": "coca-cola", "quantity": 1.0,
                           "unit": "pcs", "category": "Colas", "location_id": None})

    monkeypatch.setattr("pantry_mcp.httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("pantry_mcp.httpx.AsyncClient.post", fake_post)
    p = pantry_mcp.Pantry("http://test/api/v1")
    result = pantry_mcp.asyncio.run(p.scan_barcode("5449000000996"))
    assert "coca-cola" in result
    assert captured["params"] == {"barcode": "5449000000996"}


def test_scan_barcode_failure(monkeypatch):
    async def fake_post(self, url, params=None, json=None):
        return _Resp(500, {"detail": "boom"})

    monkeypatch.setattr("pantry_mcp.httpx.AsyncClient.post", fake_post)
    p = pantry_mcp.Pantry("http://test/api/v1")
    result = pantry_mcp.asyncio.run(p.scan_barcode("9999999999999"))
    assert "Scan failed" in result


def test_mcp_server_registers_tools():
    names = [t.name for t in pantry_mcp.asyncio.run(pantry_mcp.server.list_tools())]
    assert "scan_barcode" in names
    assert "add_item" in names
    assert "list_items" in names
    assert "delete_item" in names
    assert len(names) == 12
