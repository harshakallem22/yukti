"""Hidden grading tests for fastapi_bug_001.

The agent never sees this file. It is copied into the workspace only after the
agent has finished, so the fix cannot be written against the grader.
"""

from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    # raise_server_exceptions=False makes an unhandled exception observable as a
    # 500 response instead of propagating into the test.
    return TestClient(create_app(), raise_server_exceptions=False)


def test_duplicate_email_returns_409():
    c = client()
    first = c.post("/users", json={"email": "ada@example.com", "name": "Ada"})
    assert first.status_code == 201

    second = c.post("/users", json={"email": "ada@example.com", "name": "Ada Again"})
    assert second.status_code == 409, (
        f"expected 409 Conflict for a duplicate email, got {second.status_code}"
    )


def test_duplicate_detection_ignores_case_and_whitespace():
    c = client()
    c.post("/users", json={"email": "grace@example.com", "name": "Grace"})
    response = c.post("/users", json={"email": "  Grace@Example.COM  ", "name": "Grace"})
    assert response.status_code == 409


def test_conflict_response_has_a_message():
    c = client()
    c.post("/users", json={"email": "alan@example.com", "name": "Alan"})
    response = c.post("/users", json={"email": "alan@example.com", "name": "Alan"})
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    body = response.json()
    assert isinstance(body, dict) and body, "conflict response should carry a JSON body"
    assert any(
        isinstance(v, str) and v for v in body.values()
    ), "conflict response should explain the conflict"


def test_distinct_emails_still_register():
    c = client()
    assert c.post("/users", json={"email": "x@example.com", "name": "X"}).status_code == 201
    assert c.post("/users", json={"email": "y@example.com", "name": "Y"}).status_code == 201
    assert len(c.get("/users").json()) == 2
