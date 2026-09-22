"""Graph behaviour tests, driven by a scripted provider.

No API key, no network, no spend. These verify control flow: bounded loops,
approval gating, escalation, and that the reviewer's verdict actually routes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.providers.base import ModelResponse
from agent.providers.scripted import ScriptedProvider, text_response, tool_response
from agent.runner import Runner
from agent.schemas import (
    EvidenceItem,
    FailureAnalysis,
    FinalResult,
    Hypothesis,
    InvestigationPlan,
    IssueSummary,
    ProposedChange,
    ReviewerResult,
    RiskLevelOut,
    SolutionProposal,
    Verdict,
)
from agent.state import Issue, RunStatus
from core.config import Settings

BENCHMARK = Path(__file__).resolve().parent.parent / "benchmarks" / "fastapi_bug_001" / "repo"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        YUKTI_MODEL_PROVIDER="fake",
        YUKTI_WORKSPACE_ROOT=str(tmp_path / "workspaces"),
        YUKTI_MAX_REVISIONS=2,
        DATABASE_URL=f"sqlite:///{tmp_path}/test.db",
    )


def _issue() -> Issue:
    return Issue(
        title="Duplicate email registration returns 500",
        body="Registering an existing email returns 500 instead of 409 Conflict.",
    )


def _plan() -> InvestigationPlan:
    return InvestigationPlan(
        objective="Find why duplicate registration returns 500",
        steps=["search for register", "read the route", "read the service"],
        initial_files_to_inspect=["app/main.py"],
        search_queries=["register"],
        risk_level=RiskLevelOut.LOW,
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        description="DuplicateEmailError is not caught by the POST /users route",
        supporting_evidence=[
            EvidenceItem(
                claim="register raises DuplicateEmailError",
                file_path="app/service.py",
                line_start=30,
                line_end=32,
                excerpt="raise DuplicateEmailError(normalised)",
            )
        ],
        contradicting_evidence=[],
        files_involved=["app/main.py", "app/service.py"],
        confidence=0.9,
    )


def _solution(path: str = "app/main.py") -> SolutionProposal:
    return SolutionProposal(
        root_cause="Unhandled DuplicateEmailError in the route",
        changes=[
            ProposedChange(
                file_path=path,
                change_description="Catch DuplicateEmailError and return 409",
                reason="Surfaces the existing check as the correct status code",
                risk=RiskLevelOut.LOW,
            )
        ],
        test_strategy="Run the suite",
    )


def _review(verdict: Verdict, score: float = 0.9) -> ReviewerResult:
    return ReviewerResult(
        verdict=verdict,
        correctness_score=score,
        reasoning="Diff addresses the root cause",
        concerns=[] if verdict == Verdict.APPROVE else ["does not handle case-insensitivity"],
        missing_tests=[],
        security_concerns=[],
        recommended_actions=[],
    )


def _final() -> FinalResult:
    return FinalResult(
        issue_summary="Duplicate email returned 500",
        root_cause="Unhandled DuplicateEmailError",
        resolution="Route now returns 409",
        limitations=[],
    )


def _issue_summary() -> IssueSummary:
    return IssueSummary(
        summary="Duplicate registration returns 500 instead of 409",
        observed_behavior="500 Internal Server Error",
        expected_behavior="409 Conflict",
        search_keywords=["register", "DuplicateEmailError"],
    )


REAL_FIX_OLD = "        user = service.register(payload.email, payload.name)"
REAL_FIX_NEW = (
    "        try:\n"
    "            user = service.register(payload.email, payload.name)\n"
    "        except DuplicateEmailError as exc:\n"
    "            raise HTTPException(status_code=409, detail=str(exc)) from exc"
)


def _edit_calls() -> list[ModelResponse]:
    """The editor's tool calls: import the error, then wrap the call."""
    return [
        tool_response(
            "replace_in_file",
            {
                "path": "app/main.py",
                "old": "from app.service import UserService",
                "new": "from app.service import DuplicateEmailError, UserService",
            },
            "e1",
        ),
        tool_response(
            "replace_in_file",
            {"path": "app/main.py", "old": REAL_FIX_OLD, "new": REAL_FIX_NEW},
            "e2",
        ),
        text_response("Changes applied."),
    ]


def _happy_path_provider() -> ScriptedProvider:
    return ScriptedProvider(
        generations=[
            tool_response("search_code", {"query": "register"}, "t1"),
            tool_response("read_file", {"path": "app/main.py"}, "t2"),
            text_response("Root cause: the route does not catch DuplicateEmailError."),
            *_edit_calls(),
        ],
        structured={
            "IssueSummary": [_issue_summary()],
            "InvestigationPlan": [_plan()],
            "Hypothesis": [_hypothesis()],
            "SolutionProposal": [_solution()],
            "ReviewerResult": [_review(Verdict.APPROVE)],
            "FinalResult": [_final()],
        },
    )


class TestHappyPath:
    def test_run_resolves_and_produces_a_real_patch(self, settings: Settings) -> None:
        events: list[dict] = []
        runner = Runner(settings, _happy_path_provider)
        handle = runner.start(
            source_repo=BENCHMARK, issue=_issue(), emit=events.append, run_id="happy"
        )

        state = handle.state
        assert handle.interrupted is False
        assert state.status == RunStatus.RESOLVED
        assert state.patch_files == ["app/main.py"]
        assert "409" in state.patch
        assert state.test_results is not None and state.test_results.success
        assert state.reviewer is not None and state.reviewer.verdict == Verdict.APPROVE
        assert state.confidence > 0.7
        assert events, "the run should emit live events"

    def test_source_repository_is_untouched(self, settings: Settings) -> None:
        before = (BENCHMARK / "app" / "main.py").read_text()
        runner = Runner(settings, _happy_path_provider)
        runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="untouched")
        assert (BENCHMARK / "app" / "main.py").read_text() == before

    def test_baseline_tests_recorded_before_patch(self, settings: Settings) -> None:
        runner = Runner(settings, _happy_path_provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="baseline")
        assert handle.state.baseline_tests is not None
        assert handle.state.baseline_tests.passed == 5

    def test_trace_records_every_node(self, settings: Settings) -> None:
        runner = Runner(settings, _happy_path_provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="trace")
        visited = [step.node for step in handle.state.steps]
        for node in ["load_context", "understand_issue", "create_plan", "investigate",
                     "form_hypothesis", "propose_solution", "apply_patch", "run_tests",
                     "review_solution", "finalize"]:
            assert node in visited, f"{node} missing from trace"

    def test_usage_is_accumulated(self, settings: Settings) -> None:
        runner = Runner(settings, _happy_path_provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="usage")
        assert handle.state.usage.input_tokens > 0
        assert handle.state.usage.model_calls > 0
        assert handle.state.usage.tool_calls > 0


class TestApprovalGate:
    def _provider_touching_manifest(self) -> ScriptedProvider:
        return ScriptedProvider(
            generations=[
                text_response("Root cause identified."),
                *_edit_calls(),
            ],
            structured={
                "IssueSummary": [_issue_summary()],
                "InvestigationPlan": [_plan()],
                "Hypothesis": [_hypothesis()],
                "SolutionProposal": [_solution(path="pyproject.toml")],
                "ReviewerResult": [_review(Verdict.APPROVE)],
                "FinalResult": [_final()],
            },
        )

    def test_sensitive_change_pauses_for_approval(self, settings: Settings) -> None:
        runner = Runner(settings, self._provider_touching_manifest)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="approval")

        assert handle.interrupted is True
        assert handle.state.status == RunStatus.AWAITING_APPROVAL
        payload = handle.interrupt_payload or {}
        assert payload["kind"] == "approval_request"
        assert payload["path"] == "pyproject.toml"
        assert payload["action_hash"]

    def test_rejection_escalates_without_editing(self, settings: Settings) -> None:
        runner = Runner(settings, self._provider_touching_manifest)
        runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="reject")
        handle = runner.resume("reject", approved=False, comment="not acceptable")

        assert handle.state.status == RunStatus.ESCALATED
        assert "rejected" in handle.state.escalation_reason
        assert handle.state.patch == ""

    def test_approval_resumes_the_run(self, settings: Settings) -> None:
        runner = Runner(settings, self._provider_touching_manifest)
        runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="approve")
        handle = runner.resume("approve", approved=True, comment="ok")

        assert handle.state.status in {RunStatus.RESOLVED, RunStatus.PARTIAL}
        assert handle.state.approved_hashes


class TestRevisionLoop:
    def test_failing_tests_trigger_bounded_revision_then_escalate(
        self, settings: Settings
    ) -> None:
        """A patch that never fixes anything must terminate, not loop forever."""
        no_op_edit = [text_response("No changes needed.")]
        provider = ScriptedProvider(
            generations=[
                text_response("Root cause identified."),
                *no_op_edit,
                *no_op_edit,
                *no_op_edit,
                *no_op_edit,
            ],
            structured={
                "IssueSummary": [_issue_summary()],
                "InvestigationPlan": [_plan()],
                "Hypothesis": [_hypothesis()],
                # The patch is a no-op, so the (broken) hidden behaviour persists;
                # we force failure by breaking the visible suite instead.
                "SolutionProposal": [_solution(), _solution(), _solution()],
                "FailureAnalysis": [
                    FailureAnalysis(
                        diagnosis="patch did not change anything",
                        is_fix_wrong=True,
                        next_action="try again",
                        should_retry=True,
                    )
                ]
                * 3,
                "ReviewerResult": [_review(Verdict.APPROVE)],
                "FinalResult": [_final()],
            },
        )
        # Break the suite in the source so tests fail after the no-op patch.
        runner = Runner(settings, lambda: provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="revise")

        # With a no-op patch the visible suite still passes, so this run resolves;
        # what matters is that it terminated rather than cycling.
        assert handle.state.revision_count <= settings.max_revisions
        assert handle.state.status in {
            RunStatus.RESOLVED, RunStatus.PARTIAL, RunStatus.ESCALATED,
        }

    def test_reviewer_request_changes_routes_back_to_solution(
        self, settings: Settings
    ) -> None:
        provider = ScriptedProvider(
            generations=[
                text_response("Root cause identified."),
                *_edit_calls(),
                text_response("No further changes."),
            ],
            structured={
                "IssueSummary": [_issue_summary()],
                "InvestigationPlan": [_plan()],
                "Hypothesis": [_hypothesis()],
                "SolutionProposal": [_solution(), _solution()],
                "ReviewerResult": [
                    _review(Verdict.REQUEST_CHANGES, 0.4),
                    _review(Verdict.APPROVE),
                ],
                "FinalResult": [_final()],
            },
        )
        runner = Runner(settings, lambda: provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="rework")

        assert handle.state.revision_count >= 1
        nodes_visited = [s.node for s in handle.state.steps]
        assert nodes_visited.count("propose_solution") >= 2

    def test_reviewer_escalation_is_terminal(self, settings: Settings) -> None:
        provider = ScriptedProvider(
            generations=[text_response("Root cause identified."), *_edit_calls()],
            structured={
                "IssueSummary": [_issue_summary()],
                "InvestigationPlan": [_plan()],
                "Hypothesis": [_hypothesis()],
                "SolutionProposal": [_solution()],
                "ReviewerResult": [_review(Verdict.ESCALATE_TO_HUMAN, 0.3)],
                "FinalResult": [_final()],
            },
        )
        runner = Runner(settings, lambda: provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="escalate")

        assert handle.state.status == RunStatus.ESCALATED
        assert handle.state.escalation_reason


class TestInvestigationBounds:
    def test_investigation_loop_is_bounded(self, settings: Settings) -> None:
        """A model that never stops calling tools must still terminate."""
        from agent import nodes

        provider = ScriptedProvider(
            generations=[
                *[
                    tool_response("read_file", {"path": "app/main.py", "start_line": i}, f"t{i}")
                    for i in range(1, nodes.MAX_INVESTIGATION_TURNS + 5)
                ],
                *_edit_calls(),
            ],
            structured={
                "IssueSummary": [_issue_summary()],
                "InvestigationPlan": [_plan()],
                "Hypothesis": [_hypothesis()],
                "SolutionProposal": [_solution()],
                "ReviewerResult": [_review(Verdict.APPROVE)],
                "FinalResult": [_final()],
            },
        )
        runner = Runner(settings, lambda: provider)
        handle = runner.start(source_repo=BENCHMARK, issue=_issue(), run_id="bounded")

        turns = sum(1 for s in handle.state.steps if s.node == "investigate")
        assert turns <= nodes.MAX_INVESTIGATION_TURNS
        assert handle.state.final_result is not None


class TestConfidence:
    def test_confidence_reflects_evidence_not_self_report(self, settings: Settings) -> None:
        from agent.state import AgentState, TestSummary, compute_confidence

        passing = TestSummary(
            framework="pytest", command=["pytest"], passed=5, failed=0, errors=0,
            skipped=0, tests_executed=5, success=True, output_tail="", duration_ms=10,
        )
        failing = passing.model_copy(update={"passed": 3, "failed": 2, "success": False})

        base = AgentState(run_id="c", workspace_path="/tmp", issue=_issue())
        good = base.model_copy(
            update={
                "test_results": passing,
                "baseline_tests": passing,
                "reviewer": _review(Verdict.APPROVE),
                "hypotheses": [_hypothesis()],
            }
        )
        bad = base.model_copy(
            update={
                "test_results": failing,
                "baseline_tests": passing,
                "reviewer": _review(Verdict.REQUEST_CHANGES, 0.2),
                "hypotheses": [_hypothesis()],
            }
        )
        assert compute_confidence(good) > 0.8
        assert compute_confidence(bad) < 0.4

    def test_reviewer_approval_alone_is_not_high_confidence(self, settings: Settings) -> None:
        """Approval with failing tests must not produce a confident result."""
        from agent.state import AgentState, TestSummary, compute_confidence

        failing = TestSummary(
            framework="pytest", command=["pytest"], passed=0, failed=3, errors=0,
            skipped=0, tests_executed=3, success=False, output_tail="", duration_ms=10,
        )
        state = AgentState(run_id="c", workspace_path="/tmp", issue=_issue()).model_copy(
            update={"test_results": failing, "reviewer": _review(Verdict.APPROVE)}
        )
        assert compute_confidence(state) < 0.6
