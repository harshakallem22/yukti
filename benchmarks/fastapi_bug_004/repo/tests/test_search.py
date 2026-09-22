from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_prefix_search():
    assert client().get("/search?q=L").json()["results"] == ["London", "Lisbon"]


def test_empty_query_returns_nothing():
    assert client().get("/search?q=").json()["results"] == []


def test_no_match():
    assert client().get("/search?q=Z").json()["results"] == []
