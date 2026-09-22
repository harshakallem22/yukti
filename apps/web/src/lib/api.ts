import type {
  Approval,
  EvaluationResult,
  EvaluationRun,
  Health,
  MetricsSummary,
  Repository,
  RunDetail,
  RunSummary,
  Step,
  ToolCall,
} from "./types";

const BASE = "/api";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Request failed (${response.status})`, response.status);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  health: () => request<Health>("/health"),

  listRepositories: () => request<Repository[]>("/repositories"),
  getRepository: (id: string) => request<Repository>(`/repositories/${id}`),
  createRepository: (body: { name: string; source_path: string }) =>
    request<Repository>("/repositories", { method: "POST", body: JSON.stringify(body) }),
  repositoryTree: (id: string) =>
    request<{ tree: string; file_count: number; truncated: boolean }>(
      `/repositories/${id}/tree`,
    ),

  listRuns: (repositoryId?: string) =>
    request<RunSummary[]>(`/runs${repositoryId ? `?repository_id=${repositoryId}` : ""}`),
  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),
  getSteps: (id: string) => request<Step[]>(`/runs/${id}/steps`),
  getToolCalls: (id: string) => request<ToolCall[]>(`/runs/${id}/tool-calls`),
  getDiff: (id: string) =>
    request<{ diff: string; files_changed: string[] }>(`/runs/${id}/diff`),
  getApproval: (id: string) => request<Approval | null>(`/runs/${id}/approval`),
  createRun: (body: {
    repository_id: string;
    issue_title: string;
    issue_body: string;
    repro_steps?: string;
    expected_behavior?: string;
    risk_mode: string;
  }) => request<RunSummary>("/runs", { method: "POST", body: JSON.stringify(body) }),
  decideApproval: (id: string, body: { approved: boolean; comment: string }) =>
    request<Approval>(`/runs/${id}/approve`, { method: "POST", body: JSON.stringify(body) }),

  listApprovals: () => request<Approval[]>("/approvals"),
  metrics: () => request<MetricsSummary>("/metrics/summary"),
  listEvaluations: () => request<EvaluationRun[]>("/evaluations"),
  evaluationResults: (id: string) =>
    request<EvaluationResult[]>(`/evaluations/${id}/results`),
};

export { ApiError };
