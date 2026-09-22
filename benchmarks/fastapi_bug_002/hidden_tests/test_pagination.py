from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_first_page_starts_at_the_first_article():
    items = client().get("/articles?page=1&size=10").json()["items"]
    assert items[0]["id"] == 1, f"page 1 should start at article 1, got {items[0]['id']}"


def test_second_page_continues_from_the_first():
    items = client().get("/articles?page=2&size=10").json()["items"]
    assert items[0]["id"] == 11


def test_last_page_returns_the_remainder():
    items = client().get("/articles?page=3&size=10").json()["items"]
    assert [i["id"] for i in items] == [21, 22, 23, 24, 25]


def test_no_article_is_unreachable():
    seen = []
    for page in (1, 2, 3):
        seen += [i["id"] for i in client().get(f"/articles?page={page}&size=10").json()["items"]]
    assert sorted(seen) == list(range(1, 26))
