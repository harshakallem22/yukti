import type { ReactNode } from "react";

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-md border border-[var(--color-line)] bg-[var(--color-panel)] ${className}`}
    >
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-[var(--color-line-soft)] px-4 py-2.5">
          <h2 className="text-[13px] font-medium text-[var(--color-ink)]">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "ok" | "warn" | "bad";
}) {
  const toneColor = {
    default: "text-[var(--color-ink)]",
    ok: "text-[var(--color-ok)]",
    warn: "text-[var(--color-warn)]",
    bad: "text-[var(--color-bad)]",
  }[tone];
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">{label}</div>
      <div className={`mt-1.5 text-xl font-semibold tabular-nums ${toneColor}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-[var(--color-muted)]">{hint}</div>}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  resolved: "bg-[var(--color-ok)]/12 text-[var(--color-ok)] border-[var(--color-ok)]/30",
  running: "bg-[var(--color-accent)]/12 text-[var(--color-accent)] border-[var(--color-accent)]/30",
  queued: "bg-[var(--color-muted)]/12 text-[var(--color-muted)] border-[var(--color-muted)]/30",
  awaiting_approval: "bg-[var(--color-warn)]/12 text-[var(--color-warn)] border-[var(--color-warn)]/30",
  partial: "bg-[var(--color-warn)]/12 text-[var(--color-warn)] border-[var(--color-warn)]/30",
  escalated: "bg-[var(--color-info)]/12 text-[var(--color-info)] border-[var(--color-info)]/30",
  failed: "bg-[var(--color-bad)]/12 text-[var(--color-bad)] border-[var(--color-bad)]/30",
  APPROVE: "bg-[var(--color-ok)]/12 text-[var(--color-ok)] border-[var(--color-ok)]/30",
  REQUEST_CHANGES: "bg-[var(--color-warn)]/12 text-[var(--color-warn)] border-[var(--color-warn)]/30",
  ESCALATE_TO_HUMAN: "bg-[var(--color-info)]/12 text-[var(--color-info)] border-[var(--color-info)]/30",
};

export function Badge({ value, title }: { value: string; title?: string }) {
  const style =
    STATUS_STYLES[value] ??
    "bg-[var(--color-muted)]/10 text-[var(--color-muted)] border-[var(--color-line)]";
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${style}`}
    >
      {value.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

export function DemoBanner() {
  return (
    <div
      role="status"
      className="mb-4 rounded-md border border-[var(--color-warn)]/40 bg-[var(--color-warn)]/10 px-4 py-2.5 text-[13px] text-[var(--color-warn)]"
    >
      <strong className="font-semibold">Demo mode.</strong> The model provider is a scripted test
      double replaying a fixed trajectory — not Yukti reasoning. Tool calls, guardrails and test
      execution are real; the model's decisions are not. Set <code>OPENAI_API_KEY</code> for real
      runs.
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--color-line)] px-6 py-10 text-center">
      <p className="text-[13px] text-[var(--color-muted)]">{title}</p>
      {hint && <p className="mt-1 text-[12px] text-[var(--color-faint)]">{hint}</p>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-6 text-[13px] text-[var(--color-muted)]">
      <span
        aria-hidden
        className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--color-line)] border-t-[var(--color-accent)]"
      />
      {label}…
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div
      role="alert"
      className="rounded-md border border-[var(--color-bad)]/40 bg-[var(--color-bad)]/10 px-4 py-3 text-[13px] text-[var(--color-bad)]"
    >
      {message}
    </div>
  );
}

export function Button({
  children,
  variant = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "danger";
}) {
  const styles = {
    default:
      "border-[var(--color-line)] bg-[var(--color-panel-2)] text-[var(--color-ink)] hover:border-[var(--color-faint)]",
    primary:
      "border-[var(--color-accent)]/50 bg-[var(--color-accent)]/15 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/25",
    danger:
      "border-[var(--color-bad)]/50 bg-[var(--color-bad)]/12 text-[var(--color-bad)] hover:bg-[var(--color-bad)]/20",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded border px-3 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-medium text-[var(--color-muted)]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-[var(--color-faint)]">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-3 py-2 text-[13px] text-[var(--color-ink)] placeholder:text-[var(--color-faint)] focus:border-[var(--color-accent)]";
