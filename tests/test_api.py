"""API tests. The run executes with the scripted provider, so no key is needed."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BENCHMARK = Path(__file__).resolve().parent.parent / "benchmarks" / "fastapi_bug_001" / "repo"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.setenv("YUKTI_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("YUKTI_WORKSPACE_ROOT", str(tmp_path / "workspaces"))

    import core.config

    core.config.get_settings.cache_clear()

    # Rebind the engine and drop the cached Runner so this test's configuration
    # takes effect. No module reloading — that would re-register the declarative
    # tables on the same MetaData.
    from apps.api.app import db, service
    from apps.api.app.main import app

    db.configure()
    service.reset_runner()

    with TestClient(app) as test_client:
        yield test_client

    core.config.get_settings.cache_clear()
    service.reset_runner()


def _wait_for(client: TestClient, run_id: str, statuses: set[str], timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.2)
    raise AssertionError(f"run stayed in {run['status']}, expected one of {statuses}")


def test_health_reports_demo_mode(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True


def test_register_repository_detects_language_and_framework(client: TestClient) -> None:
    response = client.post(
        "/api/repositories", json={"name": "users-api", "source_path": str(BENCHMARK)}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["language"] == "python"
    assert body["test_framework"] == "pytest"
    assert body["file_count"] > 0


def test_register_repository_rejects_bad_path(client: TestClient) -> None:
    response = client.post(
        "/api/repositories", json={"name": "nope", "source_path": "/does/not/exist"}
    )
    assert response.status_code == 400


def test_cors_rejects_wildcard_config() -> None:
    """A wildcard origin on an API that executes code must fail at config load."""
    from pydantic import ValidationError

    from core.config import Settings

    with pytest.raises(ValidationError):
        Settings(YUKTI_CORS_ORIGINS="*")


class TestRunLifecycle:
    def _repo_id(self, client: TestClient) -> str:
        return client.post(
            "/api/repositories", json={"name": "users-api", "source_path": str(BENCHMARK)}
        ).json()["id"]

    def test_run_is_created_and_marked_demo(self, client: TestClient) -> None:
        run = client.post(
            "/api/runs",
            json={
                "repository_id": self._repo_id(client),
                "issue_title": "Duplicate email returns 500",
                "issue_body": "Should return 409 Conflict instead.",
            },
        ).json()
        assert run["demo_mode"] is True
        assert run["status"] in {"queued", "running"}

    def test_run_reaches_a_terminal_state_and_persists_trace(self, client: TestClient) -> None:
        run_id = client.post(
            "/api/runs",
            json={
                "repository_id": self._repo_id(client),
                "issue_title": "Duplicate email returns 500",
                "issue_body": "Should return 409 Conflict instead.",
            },
        ).json()["id"]

        run = _wait_for(client, run_id, {"resolved", "partial", "failed", "escalated"})
        # The scripted provider has no script for this graph path beyond the
        # happy path, so assert on the machinery rather than the outcome.
        assert run["status"] in {"resolved", "partial", "failed", "escalated"}

        steps = client.get(f"/api/runs/{run_id}/steps").json()
        assert isinstance(steps, list)
        assert client.get(f"/api/runs/{run_id}/diff").status_code == 200
        assert client.get(f"/api/runs/{run_id}/tool-calls").status_code == 200

    def test_unknown_repository_is_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/runs",
            json={"repository_id": "nope", "issue_title": "x y z", "issue_body": "a b c"},
        )
        assert response.status_code == 404

    def test_missing_run_is_404(self, client: TestClient) -> None:
        assert client.get("/api/runs/missing").status_code == 404

    def test_approve_rejects_run_not_awaiting_approval(self, client: TestClient) -> None:
        run_id = client.post(
            "/api/runs",
            json={
                "repository_id": self._repo_id(client),
                "issue_title": "Duplicate email returns 500",
                "issue_body": "Should return 409 Conflict instead.",
            },
        ).json()["id"]
        _wait_for(client, run_id, {"resolved", "partial", "failed", "escalated"})

        response = client.post(f"/api/runs/{run_id}/approve", json={"approved": True})
        assert response.status_code == 409


def test_metrics_summary_shape(client: TestClient) -> None:
    body = client.get("/api/metrics/summary").json()
    for key in ["total_runs", "resolved", "success_rate", "avg_cost_usd", "pending_approvals"]:
        assert key in body


def test_evaluations_endpoint_empty(client: TestClient) -> None:
    assert client.get("/api/evaluations").json() == []
