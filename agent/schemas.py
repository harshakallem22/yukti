"""Structured LLM outputs.

Every model output that drives control flow is a schema, never prose. Fields avoid
defaults on purpose: OpenAI strict structured-output mode requires all properties
to be present, so the model must emit an explicit (possibly empty) value rather
than omitting a field and leaving us to guess what it meant.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RiskLevelOut(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verdict(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class IssueSummary(BaseModel):
    summary: str = Field(description="One or two sentences restating the problem")
    observed_behavior: str
    expected_behavior: str
    search_keywords: list[str] = Field(
        description="Identifiers likely to appear in the relevant code, e.g. function names"
    )


class InvestigationPlan(BaseModel):
    objective: str
    steps: list[str] = Field(description="Ordered investigation steps, 3-6 items")
    initial_files_to_inspect: list[str]
    search_queries: list[str]
    risk_level: RiskLevelOut


class EvidenceItem(BaseModel):
    claim: str = Field(description="What this evidence establishes")
    file_path: str
    line_start: int
    line_end: int
    excerpt: str = Field(description="The relevant code, at most a few lines")


class Hypothesis(BaseModel):
    description: str = Field(description="The suspected root cause, stated precisely")
    supporting_evidence: list[EvidenceItem]
    contradicting_evidence: list[str]
    files_involved: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class ProposedChange(BaseModel):
    file_path: str
    change_description: str
    reason: str
    risk: RiskLevelOut


class SolutionProposal(BaseModel):
    root_cause: str
    changes: list[ProposedChange]
    test_strategy: str = Field(description="Which tests to run and why they prove the fix")


class ReviewerResult(BaseModel):
    verdict: Verdict
    correctness_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Why this verdict, citing the diff and test results")
    concerns: list[str]
    missing_tests: list[str]
    security_concerns: list[str]
    recommended_actions: list[str]


class FailureAnalysis(BaseModel):
    diagnosis: str = Field(description="Why the tests failed")
    is_fix_wrong: bool = Field(description="True if the patch is wrong, false if the test setup is")
    next_action: str
    should_retry: bool


class FinalResult(BaseModel):
    issue_summary: str
    root_cause: str
    resolution: str
    limitations: list[str] = Field(description="What this fix does not cover")
