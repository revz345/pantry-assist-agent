from fastapi.testclient import TestClient


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_list_items(client: TestClient):
    # Create location first
    loc_response = client.post("/api/v1/locations", json={"name": "Pantry"})
    assert loc_response.status_code == 201
    loc_id = loc_response.json()["id"]

    # Create item
    item_data = {"name": "Apples", "quantity": 5, "unit": "pcs", "location_id": loc_id}
    response = client.post("/api/v1/items", json=item_data)
    assert response.status_code == 201
    assert response.json()["name"] == "Apples"
    assert response.json()["quantity"] == 5
    assert response.json()["location_id"] == loc_id
    item_id = response.json()["id"]

    # List items
    response = client.get("/api/v1/items")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == item_id


def test_get_item(client: TestClient):
    loc_response = client.post("/api/v1/locations", json={"name": "Fridge"})
    loc_id = loc_response.json()["id"]

    item_data = {"name": "Milk", "quantity": 1, "unit": "l", "location_id": loc_id}
    create_resp = client.post("/api/v1/items", json=item_data)
    item_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Milk"


def test_update_item(client: TestClient):
    loc_response = client.post("/api/v1/locations", json={"name": "Pantry"})
    loc_id = loc_response.json()["id"]

    item_data = {"name": "Bread", "quantity": 1, "unit": "pcs", "location_id": loc_id}
    create_resp = client.post("/api/v1/items", json=item_data)
    item_id = create_resp.json()["id"]

    response = client.patch(f"/api/v1/items/{item_id}", json={"quantity": 2})
    assert response.status_code == 200
    assert response.json()["quantity"] == 2


def test_delete_item(client: TestClient):
    loc_response = client.post("/api/v1/locations", json={"name": "Pantry"})
    loc_id = loc_response.json()["id"]

    item_data = {"name": "Eggs", "quantity": 12, "unit": "pcs", "location_id": loc_id}
    create_resp = client.post("/api/v1/items", json=item_data)
    item_id = create_resp.json()["id"]

    response = client.delete(f"/api/v1/items/{item_id}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 404


def test_locations_crud(client: TestClient):
    # Create
    response = client.post("/api/v1/locations", json={"name": "Freezer", "description": "Deep freeze"})
    assert response.status_code == 201
    loc_id = response.json()["id"]

    # List
    response = client.get("/api/v1/locations")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Get
    response = client.get(f"/api/v1/locations/{loc_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Freezer"

    # Update
    response = client.patch(f"/api/v1/locations/{loc_id}", json={"description": "Updated"})
    assert response.status_code == 200
    assert response.json()["description"] == "Updated"

    # Delete
    response = client.delete(f"/api/v1/locations/{loc_id}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/locations/{loc_id}")
    assert response.status_code == 404


def test_expiry_reminders(client: TestClient):
    from datetime import date, timedelta
    loc_response = client.post("/api/v1/locations", json={"name": "Pantry"})
    loc_id = loc_response.json()["id"]

    # Create expiring item
    expiring_date = (date.today() + timedelta(days=3)).isoformat()
    client.post("/api/v1/items", json={"name": "Yogurt", "quantity": 2, "unit": "pcs", "location_id": loc_id, "expiry_date": expiring_date})

    # Create expired item
    expired_date = (date.today() - timedelta(days=1)).isoformat()
    client.post("/api/v1/items", json={"name": "Old Cheese", "quantity": 1, "unit": "pcs", "location_id": loc_id, "expiry_date": expired_date})

    # Create fresh item
    client.post("/api/v1/items", json={"name": "Fresh Apples", "quantity": 5, "unit": "pcs", "location_id": loc_id})

    # Get expiring
    response = client.get("/api/v1/reminders/expiring?days=7")
    assert response.status_code == 200
    expiring = response.json()
    assert len(expiring) >= 1
    assert any(i["name"] == "Yogurt" for i in expiring)

    # Get expired
    response = client.get("/api/v1/reminders/expired")
    assert response.status_code == 200
    expired = response.json()
    assert len(expired) >= 1
    assert any(i["name"] == "Old Cheese" for i in expired)


def test_scan_item(client: TestClient):
    barcode = "1234567890123"
    response = client.post(f"/api/v1/items/scan?barcode={barcode}")
    assert response.status_code == 200
    assert response.json()["barcode"] == barcode

    # Scan again - should return existing
    response = client.post(f"/api/v1/items/scan?barcode={barcode}")
    assert response.status_code == 200
    assert response.json()["barcode"] == barcode