from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def results(q: str) -> list[str]:
    return client().get(f"/search?q={q}").json()["results"]


def test_lowercase_query_matches():
    assert results("l") == ["London", "Lisbon"], "search should ignore case"


def test_uppercase_query_matches():
    assert results("BER") == ["Berlin", "Bern"]


def test_mixed_case_query_matches():
    assert results("mAn") == ["Manchester"]


def test_exact_case_still_works():
    assert results("L") == ["London", "Lisbon"]
    assert results("") == []
