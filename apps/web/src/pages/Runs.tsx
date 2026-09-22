import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { cost, duration, percent, relativeTime } from "../lib/format";
import { Badge, Button, Empty, ErrorNote, Spinner } from "../components/ui";

export function Runs() {
  const [params] = useSearchParams();
  const repositoryId = params.get("repository") ?? undefined;

  const runs = useQuery({
    queryKey: ["runs", repositoryId],
    queryFn: () => api.listRuns(repositoryId),
    refetchInterval: 4000,
  });

  return (
    <>
      <header className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold">Agent Runs</h1>
          <p className="text-[13px] text-[var(--color-muted)]">
            Every investigation, with its cost, trajectory and outcome.
          </p>
        </div>
        <Link to="/runs/new">
          <Button variant="primary">New run</Button>
        </Link>
      </header>

      {runs.isLoading && <Spinner />}
      {runs.error && <ErrorNote error={runs.error} />}

      {runs.data &&
        (runs.data.length === 0 ? (
          <Empty title="No runs yet." hint="Start an investigation from a registered repository." />
        ) : (
          <div className="overflow-x-auto rounded-md border border-[var(--color-line)]">
            <table className="w-full text-[13px]">
              <caption className="sr-only">Agent runs</caption>
              <thead className="bg-[var(--color-panel)] text-[11px] uppercase tracking-wide text-[var(--color-faint)]">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">Issue</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">Reviewer</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Conf.</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Steps</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Tools</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Cost</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Time</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line-soft)] bg-[var(--color-panel)]">
                {runs.data.map((run) => (
                  <tr key={run.id} className="hover:bg-[var(--color-panel-2)]">
                    <td className="px-3 py-2"><Badge value={run.status} /></td>
                    <td className="max-w-sm px-3 py-2">
                      <Link
                        to={`/runs/${run.id}`}
                        className="block truncate text-[var(--color-ink)] hover:text-[var(--color-accent)]"
                      >
                        {run.issue_title}
                      </Link>
                      {run.demo_mode && (
                        <span className="text-[11px] text-[var(--color-warn)]">demo mode</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {run.reviewer_verdict ? <Badge value={run.reviewer_verdict} /> : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {run.confidence ? percent(run.confidence, 0) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[var(--color-muted)]">
                      {run.step_count}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[var(--color-muted)]">
                      {run.tool_call_count}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[var(--color-muted)]">
                      {cost(run.cost_usd)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[var(--color-muted)]">
                      {duration(run.latency_ms)}
                    </td>
                    <td className="px-3 py-2 text-right text-[var(--color-faint)]">
                      {relativeTime(run.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </>
  );
}
