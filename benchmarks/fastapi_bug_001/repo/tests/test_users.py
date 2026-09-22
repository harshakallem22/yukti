from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_register_user_returns_201():
    response = client().post("/users", json={"email": "ada@example.com", "name": "Ada"})
    assert response.status_code == 201
    assert response.json()["email"] == "ada@example.com"


def test_email_is_normalised():
    response = client().post("/users", json={"email": "  Ada@Example.COM ", "name": "Ada"})
    assert response.status_code == 201
    assert response.json()["email"] == "ada@example.com"


def test_get_user_returns_registered_user():
    c = client()
    created = c.post("/users", json={"email": "grace@example.com", "name": "Grace"}).json()
    response = c.get(f"/users/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Grace"


def test_get_unknown_user_returns_404():
    assert client().get("/users/999").status_code == 404


def test_list_users():
    c = client()
    c.post("/users", json={"email": "a@example.com", "name": "A"})
    c.post("/users", json={"email": "b@example.com", "name": "B"})
    assert len(c.get("/users").json()) == 2
