from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_unknown_product_returns_404():
    response = client().get("/products/999")
    assert response.status_code == 404, (
        f"missing product should be 404, got {response.status_code}"
    )


def test_known_products_still_work():
    assert client().get("/products/1").status_code == 200
    assert client().get("/products/1").json()["name"] == "Keyboard"
