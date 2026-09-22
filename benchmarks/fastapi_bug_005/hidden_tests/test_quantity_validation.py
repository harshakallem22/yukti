from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_negative_quantity_is_rejected():
    response = client().post("/orders", json={"sku": "ABC", "quantity": -5})
    assert response.status_code in (400, 422), (
        f"negative quantity should be rejected, got {response.status_code}"
    )


def test_zero_quantity_is_rejected():
    assert client().post("/orders", json={"sku": "ABC", "quantity": 0}).status_code in (400, 422)


def test_no_negative_total_is_ever_created():
    response = client().post("/orders", json={"sku": "ABC", "quantity": -5})
    if response.status_code == 201:
        assert response.json()["total"] >= 0, "a negative total should never be created"


def test_valid_orders_still_work():
    response = client().post("/orders", json={"sku": "ABC", "quantity": 3})
    assert response.status_code == 201
    assert response.json()["total"] == 37.5
