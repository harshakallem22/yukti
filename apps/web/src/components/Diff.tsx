import { Empty } from "./ui";

/** Minimal unified-diff renderer. A syntax-highlighting dependency would be
 *  weight for one screen; line classification is all this view needs. */
export function Diff({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <Empty title="No changes were produced by this run." />;
  }

  return (
    <pre className="mono overflow-x-auto rounded border border-[var(--color-line)] bg-[var(--color-surface)] text-[12px] leading-[1.55]">
      <code>
        {diff.split("\n").map((line, index) => {
          let className = "text-[var(--color-muted)]";
          if (line.startsWith("+++") || line.startsWith("---")) {
            className = "text-[var(--color-faint)]";
          } else if (line.startsWith("@@")) {
            className = "bg-[var(--color-info)]/10 text-[var(--color-info)]";
          } else if (line.startsWith("+")) {
            className = "bg-[var(--color-ok)]/10 text-[var(--color-ok)]";
          } else if (line.startsWith("-")) {
            className = "bg-[var(--color-bad)]/10 text-[var(--color-bad)]";
          } else if (line.startsWith("diff --git")) {
            className = "text-[var(--color-ink)] font-semibold";
          }
          return (
            <div key={index} className={`whitespace-pre px-3 ${className}`}>
              {line || " "}
            </div>
          );
        })}
      </code>
    </pre>
  );
}
