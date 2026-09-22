from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import ApprovalRequired, PathTraversalError, PolicyViolation, ToolError
from guardrails.policy import approval_hash
from tools import git, repository, testing
from tools.context import ToolContext
from tools.registry import ToolInvoker


class TestRepositoryTools:
    def test_tree_lists_files(self, ctx: ToolContext) -> None:
        result = repository.get_repository_tree(ctx)
        assert "service.py" in result["tree"]
        assert result["file_count"] >= 4

    def test_tree_skips_git_internals(self, ctx: ToolContext) -> None:
        assert ".git/" not in repository.get_repository_tree(ctx)["tree"]

    def test_read_file_is_line_numbered(self, ctx: ToolContext) -> None:
        result = repository.read_file(ctx, "src/service.py")
        assert "    1 | def register_user(email):" in result["content"]
        assert result["windowed"] is False

    def test_read_file_window(self, ctx: ToolContext) -> None:
        result = repository.read_file(ctx, "src/service.py", start_line=2, end_line=3)
        assert result["start_line"] == 2
        assert result["end_line"] == 3
        assert result["windowed"] is True
        assert len(result["content"].splitlines()) == 2

    def test_read_missing_file(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            repository.read_file(ctx, "src/nope.py")

    def test_read_binary_rejected(self, ctx: ToolContext) -> None:
        (ctx.workspace / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        with pytest.raises(ToolError):
            repository.read_file(ctx, "blob.bin")

    def test_search_finds_matches_with_locations(self, ctx: ToolContext) -> None:
        result = repository.search_code(ctx, "register_user")
        assert result["match_count"] >= 1
        match = result["matches"][0]
        assert match["path"] == "src/service.py"
        assert match["line"] == 1

    def test_search_is_case_insensitive_by_default(self, ctx: ToolContext) -> None:
        assert repository.search_code(ctx, "REGISTER_USER")["match_count"] >= 1

    def test_search_file_pattern_filter(self, ctx: ToolContext) -> None:
        assert repository.search_code(ctx, "def", file_pattern="*.md")["match_count"] == 0
        assert repository.search_code(ctx, "def", file_pattern="src/*.py")["match_count"] >= 1

    def test_search_regex(self, ctx: ToolContext) -> None:
        result = repository.search_code(ctx, r"def \w+_user", regex=True)
        assert result["match_count"] == 1

    def test_search_invalid_regex(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            repository.search_code(ctx, "(unclosed", regex=True)

    def test_search_skips_ignored_directories(self, ctx: ToolContext) -> None:
        junk = ctx.workspace / "node_modules" / "pkg"
        junk.mkdir(parents=True)
        (junk / "index.js").write_text("register_user()\n")
        paths = [m["path"] for m in repository.search_code(ctx, "register_user")["matches"]]
        assert not any("node_modules" in p for p in paths)

    def test_find_files(self, ctx: ToolContext) -> None:
        assert repository.find_files(ctx, "*.py")["count"] == 3
        assert repository.find_files(ctx, "test_*.py")["files"] == ["tests/test_service.py"]

    def test_list_directory(self, ctx: ToolContext) -> None:
        result = repository.list_directory(ctx, "src")
        assert sorted(f["name"] for f in result["files"]) == ["helpers.py", "service.py"]

    def test_traversal_blocked_at_tool_level(self, ctx: ToolContext) -> None:
        with pytest.raises(PathTraversalError):
            repository.read_file(ctx, "../../../etc/passwd")


class TestGitTools:
    def test_diff_is_empty_on_clean_repo(self, ctx: ToolContext) -> None:
        assert git.git_diff(ctx)["is_empty"] is True

    def test_diff_reports_changes(self, ctx: ToolContext) -> None:
        (ctx.workspace / "src" / "service.py").write_text("def register_user(email):\n    pass\n")
        result = git.git_diff(ctx)
        assert result["is_empty"] is False
        assert result["files_changed"] == ["src/service.py"]
        assert result["lines_removed"] > 0

    def test_status_reports_modified(self, ctx: ToolContext) -> None:
        (ctx.workspace / "README.md").write_text("# changed\n")
        result = git.git_status(ctx)
        assert result["clean"] is False
        assert result["changes"][0]["path"] == "README.md"

    def test_log(self, ctx: ToolContext) -> None:
        commits = git.git_log(ctx)["commits"]
        assert len(commits) == 1
        assert commits[0]["subject"] == "init"


class TestTestingTools:
    def test_detects_pytest_from_test_files(self, ctx: ToolContext) -> None:
        assert testing.detect_test_framework(ctx)["framework"] == "pytest"

    def test_detects_unknown(self, tmp_path: Path) -> None:
        from sandbox.local import LocalWorkspaceExecutor

        empty = tmp_path / "empty"
        empty.mkdir()
        bare_ctx = ToolContext(executor=LocalWorkspaceExecutor(empty))
        assert testing.detect_test_framework(bare_ctx)["framework"] == "unknown"

    def test_run_tests_reports_counts(self, ctx: ToolContext) -> None:
        result = testing.run_tests(ctx)
        assert result["passed"] == 1
        assert result["success"] is True

    def test_failing_tests_are_reported(self, ctx: ToolContext) -> None:
        (ctx.workspace / "tests" / "test_service.py").write_text(
            "def test_ok():\n    assert True\n\ndef test_bad():\n    assert False\n"
        )
        result = testing.run_tests(ctx)
        assert result["passed"] == 1
        assert result["failed"] == 1
        assert result["success"] is False

    def test_zero_tests_is_not_success(self, ctx: ToolContext) -> None:
        """A green exit code with nothing executed proves nothing."""
        (ctx.workspace / "tests" / "test_service.py").write_text("# no tests here\n")
        result = testing.run_tests(ctx)
        assert result["tests_executed"] == 0
        assert result["success"] is False


class TestToolInvoker:
    def test_invoke_dispatches(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke("search_code", {"query": "register_user"})
        assert result["match_count"] >= 1
        assert invoker.call_count == 1

    def test_unknown_tool(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            ToolInvoker(ctx=ctx).invoke("delete_everything", {})

    def test_missing_required_argument(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            ToolInvoker(ctx=ctx).invoke("read_file", {})

    def test_unknown_argument_rejected(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            ToolInvoker(ctx=ctx).invoke("read_file", {"path": "README.md", "sudo": True})

    def test_tool_errors_become_observations(self, ctx: ToolContext) -> None:
        """A failing tool returns an error observation so the agent can adapt,
        rather than crashing the run."""
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke("read_file", {"path": "does/not/exist.py"})
        assert result["status"] == "error"
        assert invoker.history[0].status == "error"

    def test_duplicate_reads_are_detected(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        invoker.invoke("read_file", {"path": "src/service.py"})
        result = invoker.invoke("read_file", {"path": "src/service.py"})
        assert invoker.duplicate_count == 1
        assert "_note" in result

    def test_distinct_reads_are_not_duplicates(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        invoker.invoke("read_file", {"path": "src/service.py"})
        invoker.invoke("read_file", {"path": "src/helpers.py"})
        assert invoker.duplicate_count == 0

    def test_sensitive_write_raises_approval_required(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        with pytest.raises(ApprovalRequired) as exc:
            invoker.invoke("write_file", {"path": "package.json", "content": "{}"})
        assert exc.value.action_hash

    def test_approval_unlocks_only_the_exact_action(self, ctx: ToolContext) -> None:
        """Security test 10: an approval binds to one action, not to the run."""
        invoker = ToolInvoker(ctx=ctx)
        granted = approval_hash(
            "package.json",
            "'package.json' is a dependency manifest; changes run third-party code",
        )
        invoker.approved_hashes.add(granted)

        invoker.invoke("write_file", {"path": "package.json", "content": "{}"})

        # A different sensitive file is not covered by that approval.
        with pytest.raises(ApprovalRequired):
            invoker.invoke("write_file", {"path": "requirements.txt", "content": "x"})

    def test_ordinary_write_needs_no_approval(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke("write_file", {"path": "src/new.py", "content": "x = 1\n"})
        assert result["created"] is True

    def test_write_outside_workspace_is_policy_violation(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke("write_file", {"path": "../../evil.py", "content": "x"})
        assert result["status"] == "error"
        assert result["error_type"] == "path_traversal"

    def test_files_examined_tracks_reads_and_writes(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        invoker.invoke("read_file", {"path": "src/service.py"})
        invoker.invoke("write_file", {"path": "src/helpers.py", "content": "y = 2\n"})
        assert invoker.files_examined() == ["src/service.py", "src/helpers.py"]


class TestEditingTools:
    def test_replace_in_file(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        invoker.invoke(
            "replace_in_file",
            {"path": "src/helpers.py", "old": "value.lower()", "new": "value.strip().lower()"},
        )
        assert "strip()" in (ctx.workspace / "src" / "helpers.py").read_text()

    def test_replace_requires_unique_match(self, ctx: ToolContext) -> None:
        """An ambiguous edit fails loudly instead of silently changing the wrong
        occurrence."""
        (ctx.workspace / "src" / "dup.py").write_text("x = 1\nx = 1\n")
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke(
            "replace_in_file", {"path": "src/dup.py", "old": "x = 1", "new": "x = 2"}
        )
        assert result["status"] == "error"
        assert result["occurrences"] == 2

    def test_replace_missing_snippet_errors(self, ctx: ToolContext) -> None:
        invoker = ToolInvoker(ctx=ctx)
        result = invoker.invoke(
            "replace_in_file", {"path": "src/helpers.py", "old": "not there", "new": "x"}
        )
        assert result["status"] == "error"


def test_policy_violation_is_not_retryable() -> None:
    assert PolicyViolation("blocked").retryable is False
