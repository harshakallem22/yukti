import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/repositories", label: "Repositories" },
  { to: "/runs", label: "Agent Runs" },
  { to: "/evaluations", label: "Evaluations" },
];

export function Layout() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });
  const { data: approvals } = useQuery({
    queryKey: ["approvals"],
    queryFn: api.listApprovals,
    refetchInterval: 5000,
  });
  const pending = approvals?.length ?? 0;

  return (
    <div className="flex h-full">
      <nav
        aria-label="Main"
        className="flex w-52 shrink-0 flex-col border-r border-[var(--color-line)] bg-[var(--color-panel)]"
      >
        <div className="border-b border-[var(--color-line-soft)] px-4 py-4">
          <div className="text-[15px] font-semibold tracking-tight">Yukti</div>
          <div className="text-[11px] text-[var(--color-faint)]">agentic engineering</div>
        </div>

        <ul className="flex-1 space-y-0.5 p-2">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center justify-between rounded px-2.5 py-1.5 text-[13px] transition-colors ${
                    isActive
                      ? "bg-[var(--color-panel-2)] text-[var(--color-ink)]"
                      : "text-[var(--color-muted)] hover:bg-[var(--color-panel-2)] hover:text-[var(--color-ink)]"
                  }`
                }
              >
                {item.label}
                {item.to === "/runs" && pending > 0 && (
                  <span className="rounded bg-[var(--color-warn)]/20 px-1.5 text-[11px] text-[var(--color-warn)]">
                    {pending}
                  </span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="space-y-1 border-t border-[var(--color-line-soft)] px-4 py-3 text-[11px] text-[var(--color-faint)]">
          <div className="flex justify-between">
            <span>provider</span>
            <span className="text-[var(--color-muted)]">{health?.provider ?? "—"}</span>
          </div>
          <div className="flex justify-between">
            <span>sandbox</span>
            <span className="text-[var(--color-muted)]">{health?.sandbox_mode ?? "—"}</span>
          </div>
          {health?.demo_mode && (
            <div className="pt-1 font-medium text-[var(--color-warn)]">demo mode</div>
          )}
        </div>
      </nav>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
