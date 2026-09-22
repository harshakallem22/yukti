import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { cost, duration, nodeLabel, percent, tokens } from "../lib/format";
import { useRunEvents } from "../lib/useRunEvents";
import { Diff } from "../components/Diff";
import { Badge, Button, DemoBanner, Empty, ErrorNote, Panel, Spinner, Stat } from "../components/ui";
import type { RunDetail as RunDetailType } from "../lib/types";

const LIVE_STATUSES = new Set(["queued", "running"]);
const TABS = ["Timeline", "Diff", "Tool calls", "Result"] as const;
type Tab = (typeof TABS)[number];

export function RunDetail() {
  const { runId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("Timeline");

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    refetchInterval: (query) =>
      LIVE_STATUSES.has(query.state.data?.status ?? "") ? 1500 : false,
  });

  const isLive = LIVE_STATUSES.has(run.data?.status ?? "");
  const { events, connected } = useRunEvents(runId, isLive);

  if (run.isLoading) return <Spinner label="Loading run" />;
  if (run.error) return <ErrorNote error={run.error} />;
  const data = run.data!;

  return (
    <>
      <header className="mb-4">
        <Link to="/runs" className="text-[12px] text-[var(--color-faint)] hover:underline">
          ← Agent runs
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold">{data.issue_title}</h1>
          <Badge value={data.status} />
          {isLive && (
            <span className="text-[11px] text-[var(--color-accent)]">
              {connected ? "● live" : "○ reconnecting"}
            </span>
          )}
        </div>
        <p className="mt-1 max-w-3xl text-[13px] text-[var(--color-muted)]">{data.issue_body}</p>
      </header>

      {data.demo_mode && <DemoBanner />}
      {data.error && (
        <div className="mb-4">
          <ErrorNote error={new Error(data.error)} />
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Phase" value={<span className="text-[13px]">{nodeLabel(data.current_phase)}</span>} />
        <Stat
          label="Confidence"
          value={data.confidence ? percent(data.confidence, 0) : "—"}
          hint="heuristic"
          tone={data.confidence > 0.7 ? "ok" : data.confidence > 0 ? "warn" : "default"}
        />
        <Stat label="Steps" value={data.step_count} />
        <Stat label="Tool calls" value={data.tool_call_count} hint={`${data.duplicate_tool_calls} duplicate`} />
        <Stat label="Tokens" value={tokens(data.input_tokens + data.output_tokens)} hint={cost(data.cost_usd)} />
        <Stat label="Latency" value={duration(data.latency_ms)} />
      </div>

      <ApprovalGate runId={runId} status={data.status} />

      <nav className="mb-4 flex gap-1 border-b border-[var(--color-line)]" aria-label="Run sections">
        {TABS.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            aria-current={tab === name}
            className={`-mb-px border-b-2 px-3 py-2 text-[13px] transition-colors ${
              tab === name
                ? "border-[var(--color-accent)] text-[var(--color-ink)]"
                : "border-transparent text-[var(--color-muted)] hover:text-[var(--color-ink)]"
            }`}
          >
            {name}
          </button>
        ))}
      </nav>

      {tab === "Timeline" && <Timeline runId={runId} live={isLive} liveEvents={events} />}
      {tab === "Diff" && <DiffTab runId={runId} files={data.patch_files} />}
      {tab === "Tool calls" && <ToolCalls runId={runId} />}
      {tab === "Result" && <Result data={data} />}
    </>
  );
}

function ApprovalGate({ runId, status }: { runId: string; status: string }) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");

  const approval = useQuery({
    queryKey: ["approval", runId],
    queryFn: () => api.getApproval(runId),
    enabled: status === "awaiting_approval",
    refetchInterval: status === "awaiting_approval" ? 2000 : false,
  });

  const decide = useMutation({
    mutationFn: (approved: boolean) => api.decideApproval(runId, { approved, comment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (status !== "awaiting_approval" || !approval.data) return null;
  const request = approval.data;

  return (
    <section className="mb-4 rounded-md border border-[var(--color-warn)]/40 bg-[var(--color-warn)]/5">
      <header className="border-b border-[var(--color-warn)]/25 px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-[var(--color-warn)]">
          Human approval required
        </h2>
      </header>
      <div className="space-y-3 p-4">
        <dl className="grid gap-2 text-[12px] sm:grid-cols-2">
          <div>
            <dt className="text-[var(--color-faint)]">Requested action</dt>
            <dd className="mono">{request.action_type}</dd>
          </div>
          <div>
            <dt className="text-[var(--color-faint)]">Affected file</dt>
            <dd className="mono">{request.path}</dd>
          </div>
          <div>
            <dt className="text-[var(--color-faint)]">Risk</dt>
            <dd><Badge value={request.risk_level} /></dd>
          </div>
          <div>
            <dt className="text-[var(--color-faint)]">Action hash</dt>
            <dd className="mono truncate text-[11px]" title={request.action_hash}>
              {request.action_hash.slice(0, 24)}…
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-[var(--color-faint)]">Reason</dt>
            <dd>{request.reason}</dd>
          </div>
        </dl>

        <p className="text-[11px] text-[var(--color-faint)]">
          Approval is bound to this exact action hash and re-verified before execution.
        </p>

        <input
          className="w-full rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-3 py-2 text-[13px]"
          placeholder="Optional comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />

        {decide.error && <ErrorNote error={decide.error} />}

        <div className="flex gap-2">
          <Button variant="primary" disabled={decide.isPending} onClick={() => decide.mutate(true)}>
            Approve
          </Button>
          <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate(false)}>
            Reject
          </Button>
        </div>
      </div>
    </section>
  );
}

function Timeline({
  runId,
  live,
  liveEvents,
}: {
  runId: string;
  live: boolean;
  liveEvents: { seq: number; type: string; node?: string; status?: string; detail?: string }[];
}) {
  const steps = useQuery({
    queryKey: ["steps", runId],
    queryFn: () => api.getSteps(runId),
    refetchInterval: live ? 2000 : false,
  });

  // While a run is live the durable trace has not been written yet, so the SSE
  // stream is the source of truth; afterwards the database is.
  const rows = live
    ? liveEvents
        .filter((event) => event.type === "step" && event.status !== "running")
        .map((event, index) => ({
          seq: index,
          node: event.node ?? "",
          status: event.status ?? "ok",
          detail: event.detail ?? "",
          latency_ms: 0,
        }))
    : (steps.data ?? []);

  if (!live && steps.isLoading) return <Spinner />;
  if (rows.length === 0) {
    return <Empty title={live ? "Waiting for the first step…" : "No trace recorded."} />;
  }

  return (
    <Panel title={`Trace — ${rows.length} steps`}>
      <ol className="space-y-0">
        {rows.map((step, index) => (
          <li key={`${step.seq}-${index}`} className="flex gap-3 py-1.5">
            <span className="mono w-8 shrink-0 pt-0.5 text-right text-[11px] text-[var(--color-faint)]">
              {index}
            </span>
            <span
              aria-hidden
              className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                step.status === "error"
                  ? "bg-[var(--color-bad)]"
                  : step.status === "escalated" || step.status === "awaiting_approval"
                    ? "bg-[var(--color-warn)]"
                    : "bg-[var(--color-ok)]"
              }`}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="text-[13px] text-[var(--color-ink)]">{nodeLabel(step.node)}</span>
                {step.latency_ms > 0 && (
                  <span className="mono text-[11px] text-[var(--color-faint)]">
                    {duration(step.latency_ms)}
                  </span>
                )}
              </div>
              {step.detail && (
                <p className="mono mt-0.5 break-words text-[11px] text-[var(--color-muted)]">
                  {step.detail}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function DiffTab({ runId, files }: { runId: string; files: string[] }) {
  const diff = useQuery({ queryKey: ["diff", runId], queryFn: () => api.getDiff(runId) });
  if (diff.isLoading) return <Spinner />;
  if (diff.error) return <ErrorNote error={diff.error} />;

  return (
    <Panel
      title={`Patch — ${files.length} file${files.length === 1 ? "" : "s"} changed`}
      action={<span className="mono text-[11px] text-[var(--color-faint)]">{files.join(", ")}</span>}
    >
      <Diff diff={diff.data?.diff ?? ""} />
    </Panel>
  );
}

function ToolCalls({ runId }: { runId: string }) {
  const calls = useQuery({ queryKey: ["tools", runId], queryFn: () => api.getToolCalls(runId) });
  if (calls.isLoading) return <Spinner />;
  if (!calls.data?.length) return <Empty title="No tool calls recorded." />;

  return (
    <Panel title={`Tool calls — ${calls.data.length}`}>
      <table className="w-full text-[12px]">
        <thead className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">
          <tr>
            <th scope="col" className="py-1.5 text-left font-medium">#</th>
            <th scope="col" className="py-1.5 text-left font-medium">Tool</th>
            <th scope="col" className="py-1.5 text-left font-medium">Arguments</th>
            <th scope="col" className="py-1.5 text-left font-medium">Result</th>
            <th scope="col" className="py-1.5 text-right font-medium">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-line-soft)]">
          {calls.data.map((call) => (
            <tr key={call.seq}>
              <td className="mono py-1.5 text-[var(--color-faint)]">{call.seq}</td>
              <td className="mono py-1.5">
                {call.tool_name}
                {call.duplicate_of !== null && (
                  <span className="ml-1.5 text-[10px] text-[var(--color-warn)]">
                    dup of #{call.duplicate_of}
                  </span>
                )}
              </td>
              <td className="mono max-w-xs truncate py-1.5 text-[var(--color-muted)]">
                {JSON.stringify(call.arguments)}
              </td>
              <td
                className={`py-1.5 ${call.status === "error" ? "text-[var(--color-bad)]" : "text-[var(--color-muted)]"}`}
              >
                {call.result_summary || call.status}
              </td>
              <td className="mono py-1.5 text-right text-[var(--color-faint)]">
                {call.duration_ms} ms
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Result({ data }: { data: RunDetailType }) {
  const final = data.final_result;
  const review = data.reviewer_result;
  const tests = data.test_results;
  const baseline = data.baseline_tests;

  return (
    <div className="space-y-4">
      <Panel title="Root cause">
        <p className="text-[13px] leading-relaxed">
          {final?.root_cause || data.root_cause || "Not determined."}
        </p>
        {final?.resolution && (
          <>
            <h3 className="mt-3 text-[12px] font-medium text-[var(--color-muted)]">Resolution</h3>
            <p className="text-[13px] leading-relaxed">{final.resolution}</p>
          </>
        )}
        {data.escalation_reason && (
          <p className="mt-3 rounded border border-[var(--color-info)]/30 bg-[var(--color-info)]/5 px-3 py-2 text-[12px] text-[var(--color-info)]">
            Escalated: {data.escalation_reason}
          </p>
        )}
      </Panel>

      {final && final.limitations.length > 0 && (
        <Panel title="Limitations">
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-[var(--color-muted)]">
            {final.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Tests">
          {tests ? (
            <dl className="space-y-1.5 text-[12px]">
              <Row label="Framework" value={tests.framework} />
              <Row label="Passed" value={String(tests.passed)} />
              <Row label="Failed" value={String(tests.failed)} />
              <Row label="Executed" value={String(tests.tests_executed)} />
              <Row
                label="Baseline (pre-patch)"
                value={baseline ? `${baseline.passed} passed / ${baseline.failed} failed` : "—"}
              />
              <Row label="Duration" value={duration(tests.duration_ms)} />
            </dl>
          ) : (
            <Empty title="Tests did not run." />
          )}
        </Panel>

        <Panel title="Reviewer verdict">
          {review ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge value={review.verdict} />
                <span className="text-[12px] text-[var(--color-muted)]">
                  correctness {percent(review.correctness_score, 0)}
                </span>
              </div>
              <p className="text-[13px] leading-relaxed">{review.reasoning}</p>
              {review.concerns.length > 0 && (
                <ConcernList title="Concerns" items={review.concerns} />
              )}
              {review.missing_tests.length > 0 && (
                <ConcernList title="Missing tests" items={review.missing_tests} />
              )}
              {review.security_concerns.length > 0 && (
                <ConcernList title="Security concerns" items={review.security_concerns} />
              )}
            </div>
          ) : (
            <Empty title="No independent review was performed." />
          )}
        </Panel>
      </div>
    </div>
  );
}

function ConcernList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">{title}</h4>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-[12px] text-[var(--color-muted)]">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[var(--color-faint)]">{label}</dt>
      <dd className="mono text-[var(--color-muted)]">{value}</dd>
    </div>
  );
}
