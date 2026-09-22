"""MCP tests — a real client/server round trip over stdio, not mocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from yukti_mcp.client import call, connect, discover

BENCHMARK = Path(__file__).resolve().parent.parent / "benchmarks" / "fastapi_bug_001" / "repo"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_tool_discovery_returns_typed_schemas() -> None:
    async with connect(BENCHMARK) as session:
        tools = await discover(session)

    names = {tool.name for tool in tools}
    assert {"repo.get_tree", "repo.search_code", "repo.read_file", "git.diff",
            "testing.run_tests"} <= names

    read_file = next(t for t in tools if t.name == "repo.read_file")
    assert read_file.description
    assert "path" in read_file.input_schema.get("properties", {})


async def test_write_tools_are_not_published() -> None:
    """The MCP surface is read-oriented on purpose: publishing write access over a
    process boundary would hand it to any client that connects."""
    async with connect(BENCHMARK) as session:
        names = {tool.name for tool in await discover(session)}
    assert not {"write_file", "replace_in_file", "repo.write_file"} & names


async def test_search_code_returns_real_matches() -> None:
    async with connect(BENCHMARK) as session:
        result = await call(session, "repo.search_code", {"query": "DuplicateEmailError"})
    assert result["match_count"] >= 1
    assert any(m["path"] == "app/service.py" for m in result["matches"])


async def test_read_file_window() -> None:
    async with connect(BENCHMARK) as session:
        result = await call(
            session, "repo.read_file", {"path": "app/main.py", "start_line": 1, "end_line": 5}
        )
    assert result["start_line"] == 1
    assert result["end_line"] == 5
    assert "Product API" not in result["content"]


async def test_path_traversal_is_refused_by_the_server() -> None:
    """The server enforces its own guardrails — it cannot assume the caller is
    Yukti's agent."""
    async with connect(BENCHMARK) as session:
        result = await call(session, "repo.read_file", {"path": "../../../../etc/passwd"})
    assert result.get("status") == "error"
    assert result.get("error_type") == "path_traversal"


async def test_denylisted_path_is_refused() -> None:
    async with connect(BENCHMARK) as session:
        result = await call(session, "repo.read_file", {"path": ".git/config"})
    assert result.get("status") == "error"


async def test_run_tests_executes_the_real_suite() -> None:
    async with connect(BENCHMARK) as session:
        result = await call(session, "testing.run_tests", {})
    assert result["framework"] == "pytest"
    assert result["passed"] == 5
    assert result["success"] is True
