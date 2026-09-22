from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_order_is_created():
    body = client().post("/orders", json={"sku": "ABC", "quantity": 2}).json()
    assert body["quantity"] == 2
    assert body["total"] == 25.0


def test_order_ids_increment():
    c = client()
    first = c.post("/orders", json={"sku": "A", "quantity": 1}).json()
    second = c.post("/orders", json={"sku": "B", "quantity": 1}).json()
    assert second["id"] == first["id"] + 1
