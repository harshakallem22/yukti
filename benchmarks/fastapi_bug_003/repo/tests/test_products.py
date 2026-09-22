from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_existing_product_is_returned():
    body = client().get("/products/1").json()
    assert body["name"] == "Keyboard"
    assert body["price"] == 49.0


def test_second_product():
    assert client().get("/products/2").json()["name"] == "Monitor"
