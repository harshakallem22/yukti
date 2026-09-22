"""Canned trajectory for demo mode.

**This is a recording, not reasoning.** It replays one fixed sequence of decisions
for the `fastapi_bug_001` benchmark so the UI, the tool loop, the guardrails and
the approval flow can be exercised with no API key.

It is honest about what it is:
- runs made with it are stored with `demo_mode = True` and badged in the UI
- the evaluation harness refuses to score them
- pointed at any other repository it will replay these same steps and fail, which
  is the correct outcome — it has no ability to adapt

For real behaviour, set `OPENAI_API_KEY` and `YUKTI_MODEL_PROVIDER=openai`.
"""

from __future__ import annotations

from agent.providers.scripted import ScriptedProvider, text_response, tool_response
from agent.schemas import (
    EvidenceItem,
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

_ROUTE_CALL = "        user = service.register(payload.email, payload.name)"
_ROUTE_FIXED = (
    "        try:\n"
    "            user = service.register(payload.email, payload.name)\n"
    "        except DuplicateEmailError as exc:\n"
    "            raise HTTPException(status_code=409, detail=str(exc)) from exc"
)


def demo_provider() -> ScriptedProvider:
    return ScriptedProvider(
        generations=[
            tool_response("get_repository_tree", {"max_depth": 3}, "d1"),
            tool_response("search_code", {"query": "register", "file_pattern": "*.py"}, "d2"),
            tool_response("read_file", {"path": "app/main.py"}, "d3"),
            tool_response("read_file", {"path": "app/service.py"}, "d4"),
            text_response(
                "Root cause found. app/service.py raises DuplicateEmailError when an email is "
                "already registered, but the POST /users route in app/main.py:25 calls "
                "service.register without catching it, so it propagates as an unhandled "
                "exception and FastAPI returns 500. Checked the response model and the "
                "email-normalisation logic — neither is the cause."
            ),
            tool_response(
                "replace_in_file",
                {
                    "path": "app/main.py",
                    "old": "from app.service import UserService",
                    "new": "from app.service import DuplicateEmailError, UserService",
                },
                "d5",
            ),
            tool_response(
                "replace_in_file",
                {"path": "app/main.py", "old": _ROUTE_CALL, "new": _ROUTE_FIXED},
                "d6",
            ),
            text_response("Both edits applied."),
        ],
        structured={
            "IssueSummary": [
                IssueSummary(
                    summary="Registering an already-registered email returns 500 instead of 409.",
                    observed_behavior="POST /users with a duplicate email returns 500.",
                    expected_behavior="It should return 409 Conflict with an explanatory message.",
                    search_keywords=["register", "DuplicateEmailError", "409", "users"],
                )
            ],
            "InvestigationPlan": [
                InvestigationPlan(
                    objective="Find why a duplicate registration produces a 500",
                    steps=[
                        "Map the repository to locate the users API",
                        "Search for the registration handler",
                        "Read the route that handles POST /users",
                        "Read the service to see what it raises",
                    ],
                    initial_files_to_inspect=["app/main.py", "app/service.py"],
                    search_queries=["register", "DuplicateEmailError"],
                    risk_level=RiskLevelOut.LOW,
                )
            ],
            "Hypothesis": [
                Hypothesis(
                    description=(
                        "UserService.register raises DuplicateEmailError, but the POST /users "
                        "route does not catch it, so it escapes as an unhandled exception and "
                        "FastAPI converts it into a 500."
                    ),
                    supporting_evidence=[
                        EvidenceItem(
                            claim="The service raises a domain error on duplicates",
                            file_path="app/service.py",
                            line_start=30,
                            line_end=32,
                            excerpt=(
                                "if normalised in self._emails:\n"
                                "    raise DuplicateEmailError(normalised)"
                            ),
                        ),
                        EvidenceItem(
                            claim="The route calls register with no exception handling",
                            file_path="app/main.py",
                            line_start=25,
                            line_end=27,
                            excerpt="user = service.register(payload.email, payload.name)",
                        ),
                    ],
                    contradicting_evidence=[],
                    files_involved=["app/main.py", "app/service.py"],
                    confidence=0.92,
                )
            ],
            "SolutionProposal": [
                SolutionProposal(
                    root_cause=(
                        "DuplicateEmailError raised by UserService.register is not handled by "
                        "the POST /users route."
                    ),
                    changes=[
                        ProposedChange(
                            file_path="app/main.py",
                            change_description=(
                                "Catch DuplicateEmailError around the register call and raise "
                                "HTTPException(409) with the error message."
                            ),
                            reason=(
                                "Surfaces the existing uniqueness check as the correct status "
                                "code without weakening the check itself."
                            ),
                            risk=RiskLevelOut.LOW,
                        )
                    ],
                    test_strategy=(
                        "Run the existing suite to confirm no regression; the duplicate case "
                        "should now return 409."
                    ),
                )
            ],
            "ReviewerResult": [
                ReviewerResult(
                    verdict=Verdict.APPROVE,
                    correctness_score=0.9,
                    reasoning=(
                        "The diff catches the domain error at the boundary and maps it to 409. "
                        "The uniqueness check in the service is untouched, so the fix addresses "
                        "the reported behaviour rather than hiding it. Existing tests still pass."
                    ),
                    concerns=[],
                    missing_tests=[
                        "No test was added for the duplicate case in the visible suite."
                    ],
                    security_concerns=[],
                    recommended_actions=["Add a regression test covering the 409 path."],
                )
            ],
            "FinalResult": [
                FinalResult(
                    issue_summary=(
                        "Registering an existing email returned 500 instead of 409 Conflict."
                    ),
                    root_cause=(
                        "The POST /users route called UserService.register without catching "
                        "DuplicateEmailError, so the domain error escaped as an unhandled "
                        "exception."
                    ),
                    resolution=(
                        "The route now catches DuplicateEmailError and raises "
                        "HTTPException(409) carrying the error message."
                    ),
                    limitations=[
                        "No regression test was added to the visible suite for the 409 path.",
                        "Other endpoints were not audited for the same unhandled-domain-error "
                        "pattern.",
                    ],
                )
            ],
        },
    )
