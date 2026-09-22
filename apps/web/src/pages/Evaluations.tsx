import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { cost, duration, percent, relativeTime } from "../lib/format";
import { Badge, Empty, ErrorNote, Panel, Spinner, Stat } from "../components/ui";

const HEADLINE = [
  ["task_success_rate", "Task Success", "Hidden tests pass after the agent's patch"],
  ["regression_safety_rate", "Regression Safety", "No previously-passing test broke"],
  ["patch_correctness_rate", "Patch Correctness", "Changed a legitimate implementation file"],
  ["policy_compliance_rate", "Policy Compliance", "No blocked operation executed"],
  ["approval_compliance_rate", "Approval Compliance", "No sensitive write without approval"],
  ["file_localization_recall", "File Localization", "Found the files that needed changing"],
] as const;

export function Evaluations() {
  const evaluations = useQuery({ queryKey: ["evaluations"], queryFn: api.listEvaluations });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const activeId = selectedId ?? evaluations.data?.[0]?.id ?? null;
  const results = useQuery({
    queryKey: ["evaluation-results", activeId],
    queryFn: () => api.evaluationResults(activeId!),
    enabled: Boolean(activeId),
  });

  if (evaluations.isLoading) return <Spinner />;
  if (evaluations.error) return <ErrorNote error={evaluations.error} />;

  const runs = evaluations.data ?? [];
  if (runs.length === 0) {
    return (
      <>
        <Header />
        <Empty
          title="No evaluation runs recorded."
          hint="Run: python -m evals.run --suite baseline"
        />
      </>
    );
  }

  const active = runs.find((run) => run.id === activeId) ?? runs[0];
  const metrics = active.aggregate_metrics as Record<string, number> & {
    demo_mode?: boolean;
    failure_categories?: Record<string, number>;
  };
  const failures = metrics.failure_categories ?? {};

  return (
    <>
      <Header />

      {metrics.demo_mode && (
        <div className="mb-4 rounded-md border border-[var(--color-warn)]/40 bg-[var(--color-warn)]/10 px-4 py-2.5 text-[13px] text-[var(--color-warn)]">
          <strong className="font-semibold">Not real metrics.</strong> This suite ran against the
          scripted provider, which replays a fixed trajectory. It verifies the harness, not the
          agent.
        </div>
      )}

      <Panel title="Evaluation runs" className="mb-4">
        <div className="flex flex-wrap gap-2">
          {runs.map((run) => (
            <button
              key={run.id}
              onClick={() => setSelectedId(run.id)}
              className={`rounded border px-3 py-1.5 text-left text-[12px] transition-colors ${
                run.id === active.id
                  ? "border-[var(--color-accent)]/60 bg-[var(--color-accent)]/10"
                  : "border-[var(--color-line)] hover:border-[var(--color-faint)]"
              }`}
            >
              <span className="block font-medium">{run.suite}</span>
              <span className="mono block text-[11px] text-[var(--color-faint)]">
                {run.case_count} cases · {run.model} · {run.git_sha} · {relativeTime(run.started_at)}
              </span>
            </button>
          ))}
        </div>
      </Panel>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        {HEADLINE.map(([key, label, hint]) => {
          const value = metrics[key] ?? 0;
          return (
            <Stat
              key={key}
              label={label}
              value={percent(value)}
              hint={hint}
              tone={value >= 0.9 ? "ok" : value >= 0.6 ? "warn" : "bad"}
            />
          );
        })}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Avg tool calls" value={(metrics.avg_tool_calls ?? 0).toFixed(1)} />
        <Stat label="Avg duplicate calls" value={(metrics.avg_duplicate_tool_calls ?? 0).toFixed(1)} hint="lower is better" />
        <Stat label="Avg latency" value={duration(metrics.avg_latency_ms ?? 0)} />
        <Stat label="Avg cost" value={cost(metrics.avg_cost_usd ?? 0)} />
      </div>

      {Object.keys(failures).length > 0 && (
        <Panel title="Failure categories" className="mb-4">
          <ul className="space-y-1.5">
            {Object.entries(failures)
              .sort((a, b) => b[1] - a[1])
              .map(([category, count]) => (
                <li key={category} className="flex items-center gap-3">
                  <span className="mono w-52 shrink-0 text-[12px]">{category}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-[var(--color-line-soft)]">
                    <div
                      className="h-full bg-[var(--color-bad)]/60"
                      style={{ width: `${(count / active.case_count) * 100}%` }}
                    />
                  </div>
                  <span className="mono w-8 text-right text-[12px] text-[var(--color-muted)]">
                    {count}
                  </span>
                </li>
              ))}
          </ul>
        </Panel>
      )}

      <Panel title="Per-case results">
        {results.isLoading && <Spinner />}
        {results.data && (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">
                <tr>
                  <th scope="col" className="py-1.5 text-left font-medium">Case</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Success</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Loc. P/R</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Regr.</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Policy</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Tools</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Cost</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Failure</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line-soft)]">
                {results.data.map((result) => (
                  <tr key={result.case_id}>
                    <td className="mono py-1.5">{result.case_id}</td>
                    <td className="py-1.5">
                      <Badge value={result.task_success ? "resolved" : "failed"} />
                    </td>
                    <td className="mono py-1.5 text-right text-[var(--color-muted)]">
                      {percent(result.file_localization_precision, 0)}/
                      {percent(result.file_localization_recall, 0)}
                    </td>
                    <td className="py-1.5 text-right">{result.regression_safety ? "✓" : "✗"}</td>
                    <td className="py-1.5 text-right">
                      {result.policy_compliance && result.approval_compliance ? "✓" : "✗"}
                    </td>
                    <td className="mono py-1.5 text-right text-[var(--color-muted)]">
                      {result.tool_calls}
                    </td>
                    <td className="mono py-1.5 text-right text-[var(--color-muted)]">
                      {cost(result.cost_usd)}
                    </td>
                    <td className="mono py-1.5 text-[var(--color-bad)]">
                      {result.failure_category || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function Header() {
  return (
    <header className="mb-5">
      <h1 className="text-lg font-semibold">Evaluations</h1>
      <p className="text-[13px] text-[var(--color-muted)]">
        Benchmark results graded by hidden tests the agent never sees.
      </p>
    </header>
  );
}
