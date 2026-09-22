export function duration(ms: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function cost(usd: number): string {
  if (!usd) return "$0.0000";
  return `$${usd.toFixed(4)}`;
}

export function percent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function tokens(count: number): string {
  if (count < 1000) return String(count);
  return `${(count / 1000).toFixed(1)}k`;
}

const NODE_LABELS: Record<string, string> = {
  load_context: "Repository loaded",
  understand_issue: "Issue understood",
  create_plan: "Investigation strategy created",
  investigate: "Investigating",
  form_hypothesis: "Root-cause hypothesis formed",
  propose_solution: "Solution proposed",
  risk_check: "Risk evaluated",
  human_approval: "Awaiting human approval",
  apply_patch: "Patch applied in sandbox",
  run_tests: "Tests executed",
  analyze_failure: "Failure analysed",
  review_solution: "Reviewer verification",
  finalize: "Final report",
  escalate: "Escalated",
  tool: "Tool call",
};

export function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node.replace(/_/g, " ");
}
