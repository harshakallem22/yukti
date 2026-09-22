import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { cost, duration, percent, relativeTime } from "../lib/format";
import { Badge, DemoBanner, Empty, ErrorNote, Panel, Spinner, Stat } from "../components/ui";

export function Dashboard() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: api.metrics,
    refetchInterval: 5000,
  });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.listRuns(), refetchInterval: 5000 });
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: api.listApprovals,
    refetchInterval: 5000,
  });

  if (metrics.isLoading) return <Spinner />;
  if (metrics.error) return <ErrorNote error={metrics.error} />;

  const m = metrics.data!;
  const finished = m.resolved + m.failed + m.escalated;

  return (
    <>
      <header className="mb-5">
        <h1 className="text-lg font-semibold">Dashboard</h1>
        <p className="text-[13px] text-[var(--color-muted)]">
          Agent run outcomes, cost and pending approvals.
        </p>
      </header>

      {health?.demo_mode && <DemoBanner />}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total runs" value={m.total_runs} hint={`${finished} finished`} />
        <Stat
          label="Success rate"
          value={percent(m.success_rate)}
          hint={`${m.resolved} resolved`}
          tone={m.success_rate >= 0.7 ? "ok" : m.success_rate > 0 ? "warn" : "default"}
        />
        <Stat label="Avg cost / run" value={cost(m.avg_cost_usd)} />
        <Stat label="Avg latency" value={duration(m.avg_latency_ms)} />
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Avg tool calls" value={m.avg_tool_calls.toFixed(1)} />
        <Stat
          label="Escalated"
          value={m.escalated}
          hint="ended honestly, not faked"
          tone={m.escalated > 0 ? "warn" : "default"}
        />
        <Stat label="Failed" value={m.failed} tone={m.failed > 0 ? "bad" : "default"} />
        <Stat
          label="Pending approvals"
          value={m.pending_approvals}
          tone={m.pending_approvals > 0 ? "warn" : "default"}
        />
      </div>

      {(approvals.data?.length ?? 0) > 0 && (
        <Panel title="Approvals waiting on you" className="mb-5">
          <ul className="space-y-2">
            {approvals.data!.map((approval) => (
              <li
                key={approval.id}
                className="flex items-center justify-between gap-4 rounded border border-[var(--color-warn)]/30 bg-[var(--color-warn)]/5 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="mono truncate text-[12px]">{approval.path}</div>
                  <div className="truncate text-[12px] text-[var(--color-muted)]">
                    {approval.reason}
                  </div>
                </div>
                <Link
                  to={`/runs/${approval.run_id}`}
                  className="shrink-0 text-[12px] text-[var(--color-accent)] hover:underline"
                >
                  Review →
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel
        title="Recent runs"
        action={
          <Link to="/runs" className="text-[12px] text-[var(--color-accent)] hover:underline">
            View all
          </Link>
        }
      >
        {runs.data && runs.data.length > 0 ? (
          <ul className="divide-y divide-[var(--color-line-soft)]">
            {runs.data.slice(0, 8).map((run) => (
              <li key={run.id}>
                <Link
                  to={`/runs/${run.id}`}
                  className="flex items-center gap-3 py-2.5 hover:bg-[var(--color-panel-2)]"
                >
                  <Badge value={run.status} />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{run.issue_title}</span>
                  {run.demo_mode && (
                    <span className="text-[11px] text-[var(--color-warn)]">demo</span>
                  )}
                  <span className="tabular-nums text-[12px] text-[var(--color-faint)]">
                    {run.tool_call_count} tools
                  </span>
                  <span className="tabular-nums text-[12px] text-[var(--color-faint)]">
                    {cost(run.cost_usd)}
                  </span>
                  <span className="w-16 text-right text-[12px] text-[var(--color-faint)]">
                    {relativeTime(run.created_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title="No agent runs yet."
            hint="Register a repository, then start an investigation."
          />
        )}
      </Panel>
    </>
  );
}
