export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "resolved"
  | "partial"
  | "failed"
  | "escalated";

export interface Repository {
  id: string;
  name: string;
  source_path: string;
  language: string;
  test_framework: string;
  file_count: number;
  created_at: string;
}

export interface RunSummary {
  id: string;
  repository_id: string;
  issue_title: string;
  status: RunStatus;
  current_phase: string;
  confidence: number;
  cost_usd: number;
  latency_ms: number;
  step_count: number;
  tool_call_count: number;
  reviewer_verdict: string;
  demo_mode: boolean;
  created_at: string;
}

export interface TestResults {
  framework: string;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  tests_executed: number;
  success: boolean;
  output_tail: string;
  duration_ms: number;
}

export interface ReviewerResult {
  verdict: string;
  correctness_score: number;
  reasoning: string;
  concerns: string[];
  missing_tests: string[];
  security_concerns: string[];
  recommended_actions: string[];
}

export interface FinalResult {
  issue_summary: string;
  root_cause: string;
  resolution: string;
  limitations: string[];
}

export interface RunDetail extends RunSummary {
  issue_body: string;
  root_cause: string;
  patch: string;
  patch_files: string[];
  final_result: FinalResult | null;
  reviewer_result: ReviewerResult | null;
  test_results: TestResults | null;
  baseline_tests: TestResults | null;
  escalation_reason: string;
  error: string;
  input_tokens: number;
  output_tokens: number;
  duplicate_tool_calls: number;
  workspace_path: string;
}

export interface Step {
  seq: number;
  node: string;
  phase: string;
  status: string;
  detail: string;
  latency_ms: number;
}

export interface ToolCall {
  seq: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  result_summary: string;
  duration_ms: number;
  duplicate_of: number | null;
}

export interface Approval {
  id: string;
  run_id: string;
  action_hash: string;
  action_type: string;
  path: string;
  reason: string;
  risk_level: string;
  status: string;
  comment: string;
  requested_at: string;
}

export interface MetricsSummary {
  total_runs: number;
  resolved: number;
  escalated: number;
  failed: number;
  success_rate: number;
  avg_cost_usd: number;
  avg_latency_ms: number;
  avg_tool_calls: number;
  pending_approvals: number;
  demo_runs: number;
}

export interface EvaluationRun {
  id: string;
  suite: string;
  git_sha: string;
  model: string;
  prompt_version: string;
  case_count: number;
  aggregate_metrics: Record<string, number | Record<string, number> | boolean>;
  started_at: string;
  ended_at: string | null;
}

export interface EvaluationResult {
  case_id: string;
  task_success: boolean;
  test_pass_rate: number;
  patch_correctness: boolean;
  regression_safety: boolean;
  file_localization_precision: number;
  file_localization_recall: number;
  policy_compliance: boolean;
  approval_compliance: boolean;
  steps: number;
  tool_calls: number;
  duplicate_tool_calls: number;
  cost_usd: number;
  latency_ms: number;
  failure_category: string;
}

export interface Health {
  status: string;
  provider: string;
  sandbox_mode: string;
  model_access: boolean;
  demo_mode: boolean;
}

export interface RunEvent {
  seq: number;
  type: string;
  node?: string;
  status?: string;
  detail?: string;
  message?: string;
}
