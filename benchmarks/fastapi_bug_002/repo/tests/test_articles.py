from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_listing_returns_page_metadata():
    body = client().get("/articles?page=1&size=10").json()
    assert body["page"] == 1
    assert body["size"] == 10
    assert body["total"] == 25


def test_page_size_is_respected():
    assert len(client().get("/articles?page=1&size=10").json()["items"]) == 10


def test_rejects_invalid_page():
    assert client().get("/articles?page=0").status_code == 422
